"""Phase A contract regressions: mocked LLM/enqueue, in-memory DB, no ComfyUI."""
import copy
import difflib
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api import shots as api
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.repositories.shot_repository import ShotRepository
from app.repositories.task import TaskRepository
from app.schemas.shot import PlanClipsRequest, PlanVideoKeyframesRequest
from app.services import clip_planner as planner, video_director_ai as ai
from app.services.dialogue_ownership import assign_dialogues_to_clips
from app.services.shot_video_service import _semantic_clip_prompt_context, get_semantic_clip_prompt
from app.services.visual_attention import prompt_projection_metadata

FIXTURES = Path(__file__).parent / "fixtures"


def frozen():
    return json.loads((FIXTURES / "video_director_phase_a.json").read_text())


def small_shot(official=True):
    data = frozen()
    dialogues = json.loads(data["shot"]["dialogues"])[:6]
    plan = {"dialogue_timeline_source": data["plan"]["dialogue_timeline_source"][:6],
            "dialogue_timeline_status": {"status": "ok"}, "canonical_visual_plan": True,
            "keyframes": [{"index": 1, "role": "START", "time_seconds": 0,
                           "description": None, "timed_visual_target": False}],
            "clip_plan_revision": 1}
    if not official:
        plan.pop("dialogue_timeline_source")
        plan.pop("dialogue_timeline_status")
    return SimpleNamespace(**{**data["shot"], "duration": 13.1, "dialogues": json.dumps(dialogues, ensure_ascii=False),
                             "video_director_plan": json.dumps(plan, ensure_ascii=False), "image_url": None,
                             "image_path": None, "keyframes": "[]"}), plan


def mock_planner(monkeypatch, shot, capture):
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            capture.append(json.loads(kwargs["user_content"]))
            return {"success": True, "content": json.dumps({"clips": [{
                "clip_index": 1, "start_time": 0, "end_time": shot.duration,
                "continuity_to_previous": "NONE", "reason": "existing story interval",
                "selected_temporal_target_ids": [], "early_composition_state_id": None,
            }]})}
    monkeypatch.setattr(planner, "LLMService", FakeLLM)
    monkeypatch.setattr(planner, "PromptTemplateService", lambda db: SimpleNamespace(
        get_default_system_template=lambda kind: SimpleNamespace(template="frozen #10A", name="fixture")))


@pytest.mark.asyncio
async def test_01_persisted_official_wins_across_all_consumers(monkeypatch):
    shot, plan = small_shot()
    # Deliberately choose a valid official B that differs from allocator A.
    plan["dialogue_timeline_source"][4].update(start_time=9.6, end_time=10.85)
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    allocated, _, _ = ai.build_dialogue_timeline({"start_time": 0, "end_time": shot.duration}, json.loads(shot.dialogues), [])
    assert allocated[4]["start_time"] == 9.55
    def no_allocator(*args):
        raise AssertionError("official timeline must bypass allocator")
    monkeypatch.setattr(ai, "build_dialogue_timeline", no_allocator)
    timeline, _ = ai.resolve_canonical_dialogue_timeline(shot)
    assert api._get_official_dialogue_timeline(None, shot, []) == timeline
    content = api._build_keyframe_planner_user_content(shot, plan, resolved_dialogue_timeline=timeline)
    assert json.loads(content.split("\n\n", 1)[1])["dialogue_timeline_source"][4]["start_time"] == 9.6
    captured = []
    mock_planner(monkeypatch, shot, captured)
    clips, validation = await planner.plan_clips(None, SimpleNamespace(id="novel"), shot, [], resolved_dialogue_timeline=timeline)
    assert validation["passed"], validation
    assert captured[0]["speech_timing_intervals"][4] == {"event_id": "D5", "start_time": 9.6, "end_time": 10.85}
    assert clips[0]["dialogue_assignment"][4]["start_time"] == 9.6
    # A stale task assignment cannot override current official B in H3 context.
    plan["clip_plan"] = clips
    stale = copy.deepcopy(clips[0]["dialogue_assignment"])
    stale[4].update(start_time=1.05, end_time=2.2, speaker="骗子1")
    context = _semantic_clip_prompt_context(plan, {"clip_index": 1, "dialogue_assignment": stale}, resolved_dialogue_timeline=timeline)
    assert (context["clip_dialogues"][4]["local_start_time"], context["clip_dialogues"][4]["local_end_time"]) == (9.6, 10.85)
    assert context["clip_dialogues"][4]["speaker"] == "皇帝"


@pytest.mark.asyncio
async def test_02_missing_official_allocates_once_then_explicitly_reuses(monkeypatch):
    shot, plan = small_shot(official=False)
    original = ai.build_dialogue_timeline
    calls = []
    def allocator(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(ai, "build_dialogue_timeline", allocator)
    timeline, status = ai.resolve_canonical_dialogue_timeline(shot, plan)
    plan.update(dialogue_timeline_source=timeline, dialogue_timeline_status=status)
    api._build_keyframe_planner_user_content(shot, plan, resolved_dialogue_timeline=timeline)
    captured = []
    mock_planner(monkeypatch, shot, captured)
    clips, validation = await planner.plan_clips(None, SimpleNamespace(id="novel"), shot, [], resolved_dialogue_timeline=timeline)
    assert validation["passed"]
    plan["clip_plan"] = clips
    context = _semantic_clip_prompt_context(plan, {"clip_index": 1}, resolved_dialogue_timeline=timeline)
    # H3's build_dialogue_timeline projection branch is deterministic; no allocator.
    local, _, h3_status = original(context["clip"], context["clip_dialogues"], [])
    assert h3_status["source"] == "official_projection"
    assert local[4]["start_time"] == timeline[4]["start_time"]
    assert len(calls) == 1
    assert "dialogue_timeline_source" not in json.loads(shot.video_director_plan)


@pytest.mark.asyncio
async def test_03_force_clip_replanning_cannot_overwrite_official(monkeypatch):
    shot, plan = small_shot()
    before = copy.deepcopy(plan["dialogue_timeline_source"])
    mock_planner(monkeypatch, shot, [])
    db = SimpleNamespace(commit=MagicMock())
    result = await api.plan_shot_clips("novel", shot.chapter_id, shot.id, PlanClipsRequest(force=True), db,
                                     SimpleNamespace(get_by_id=lambda id: SimpleNamespace(id=id)),
                                     SimpleNamespace(get_by_id=lambda id: shot))
    assert result["data"]["validation"]["passed"]
    assert json.loads(shot.video_director_plan)["dialogue_timeline_source"] == before
    context = _semantic_clip_prompt_context(json.loads(shot.video_director_plan), {"clip_index": 1})
    assert context["clip_dialogues"][4]["local_start_time"] == 9.55
    assert before[4]["end_time"] == 10.8


def test_04_shot_seconds_project_to_local_without_mutation():
    timeline = [{"id": "D5", "speaker": "皇帝", "text": "它有多漂亮？", "start_time": 35.0, "end_time": 36.2}]
    before = copy.deepcopy(timeline)
    clip = {"clip_index": 2, "start_time": 30, "end_time": 45}
    metadata = ai.build_execution_intent_metadata(timeline, clip)
    assert metadata["execution_intent"]["canonical_time_base"] == "SHOT_SECONDS"
    assert metadata["execution_intent"]["time_base"] == "CLIP_LOCAL_SECONDS"
    assert metadata["execution_intent"]["events"] == [{"dialogue_id": "D5", "intended_window": {"start": 5.0, "end": 6.2}}]
    assert timeline == before
    assert all(key not in metadata["execution_intent"]["events"][0] for key in ["text", "speaker", "start_time", "end_time"])


@pytest.mark.parametrize("damage", ["speaker", "order", "missing", "extra", "duplicate", "nan", "text", "overlap"])
def test_05_invalid_official_identity_is_not_silently_reallocated(monkeypatch, damage):
    shot, plan = small_shot()
    events = plan["dialogue_timeline_source"]
    if damage == "speaker": events[4]["speaker"] = "骗子1"
    elif damage == "order": events[0], events[1] = events[1], events[0]
    elif damage == "missing": events.pop()
    elif damage == "extra": events.append({**events[-1], "id": "D7"})
    elif damage == "duplicate": events[1]["id"] = "D1"
    elif damage == "nan": events[4]["start_time"] = float("nan")
    elif damage == "text": events[4]["text"] += "额外台词"
    elif damage == "overlap": events[4]["start_time"] = 8.35
    monkeypatch.setattr(ai, "build_dialogue_timeline", lambda *args: pytest.fail("invalid official may not invoke allocator"))
    assert not api._timeline_matches_shot_dialogues(events, json.loads(shot.dialogues))
    with pytest.raises(ValueError, match="CANONICAL_DIALOGUE_TIMELINE_INVALID"):
        ai.resolve_canonical_dialogue_timeline(shot, plan)


@pytest.mark.asyncio
async def test_06_existing_clip_and_visual_plan_reads_do_not_write(monkeypatch):
    shot, plan = small_shot()
    clips = [{"clip_index": 1, "start_time": 0, "end_time": shot.duration, "capability": "GENERATE"}]
    assignments, validation = assign_dialogues_to_clips(json.loads(shot.dialogues), clips, plan["dialogue_timeline_source"])
    clips[0]["dialogue_assignment"] = assignments[0]["dialogues"]
    plan.update(clip_plan=clips, clip_plan_validation={"passed": True, "findings": [], "blocking": []})
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    before = shot.video_director_plan
    db = SimpleNamespace(commit=MagicMock())
    repo = SimpleNamespace(get_by_id=lambda *args: shot)
    novel = SimpleNamespace(get_by_id=lambda *args: SimpleNamespace(id="novel"))
    await api.plan_shot_clips("novel", shot.chapter_id, shot.id, PlanClipsRequest(), db, novel, repo)
    await api.plan_video_keyframes("novel", shot.chapter_id, shot.id, PlanVideoKeyframesRequest(), db, novel,
                                   SimpleNamespace(get_by_id=lambda *args: SimpleNamespace(id=shot.chapter_id)), repo)
    assert shot.video_director_plan == before
    db.commit.assert_not_called()
    semantics = ai.read_execution_semantics(clips[0])
    assert semantics["execution_intent"]["version"] == "legacy"
    assert semantics["execution_intent"]["visual_support_status"] == "unknown"
    assert semantics["realization_review"] == "unreviewed"


def test_07_old_approved_task_remains_approved_and_unreviewed(db_session):
    task = Task(id="legacy-approved", type="shot_video", name="old artifact", status="completed",
                metadata_json=json.dumps({"approval_status": "APPROVED"}))
    db_session.add(task)
    db_session.commit()
    before = task.metadata_json
    semantics = ai.read_execution_semantics(json.loads(task.metadata_json))
    assert semantics["realization_review"] == "unreviewed"
    assert semantics["execution_intent"]["version"] == "legacy"
    assert task.status == "completed" and json.loads(task.metadata_json)["approval_status"] == "APPROVED"
    assert task.metadata_json == before and not db_session.dirty


@pytest.mark.asyncio
@pytest.mark.parametrize("official", [True, False])
async def test_08_new_semantic_task_records_intent_without_executing(db_session, monkeypatch, official):
    fake, plan = small_shot(official)
    novel = Novel(title="Phase A temporary novel")
    db_session.add(novel); db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="temporary chapter")
    db_session.add(chapter); db_session.flush()
    plan["canonical_visual_plan"] = False
    plan["clip_plan"] = [{"clip_index": 1, "start_time": 0, "end_time": fake.duration,
                           "planned_duration": fake.duration, "capability": "GENERATE"}]
    shot = Shot(chapter_id=chapter.id, index=3, duration=fake.duration, dialogues=fake.dialogues,
                characters=fake.characters, video_director_plan=json.dumps(plan, ensure_ascii=False))
    db_session.add(shot); db_session.commit()
    workflow = SimpleNamespace(id="mock-workflow", name="frozen", type="multi_reference_video")
    monkeypatch.setattr(api, "WorkflowRepository", lambda db: SimpleNamespace(get_active_by_type=lambda type: workflow))
    monkeypatch.setattr(api.TaskService, "validate_workflow_node_mapping", lambda *args: (True, ""))
    monkeypatch.setattr(api, "resolve_clip_reference_resources", lambda *args: [])
    monkeypatch.setattr(api, "compile_generate_clip", lambda *args, **kwargs: {
        "execution_contract": {"version": 1, "capability": "GENERATE", "artifact_kind": "CLIP_ONLY"},
        "video_reference_manifest": {"version": 1, "references": []}})
    enqueue = MagicMock()
    monkeypatch.setattr(api, "enqueue_shot_video_task", enqueue)
    original = ai.build_dialogue_timeline
    allocations = []
    def allocate(*args):
        allocations.append(args)
        return original(*args)
    monkeypatch.setattr(ai, "build_dialogue_timeline", allocate)
    result = await api.execute_semantic_clip(novel.id, chapter.id, shot.id, 1,
        api.SemanticClipGenerateRequest(clip_plan_revision=1), db_session,
        SimpleNamespace(get_by_id=lambda id: novel), SimpleNamespace(get_by_id=lambda *args: chapter),
        TaskRepository(db_session), ShotRepository(db_session))
    task = db_session.get(Task, result["data"]["taskId"])
    metadata = json.loads(task.metadata_json)
    intent = metadata["execution_intent"]
    assert intent["canonical_timeline_source"] == "shots.video_director_plan.dialogue_timeline_source"
    assert len(intent["canonical_timeline_sha256"]) == 64
    assert intent["time_base"] == "CLIP_LOCAL_SECONDS"
    assert intent["events"][4] == {"dialogue_id": "D5", "intended_window": {"start": 9.55, "end": 10.8}}
    assert intent["timing_reliability"] == intent["speaker_realization_reliability"] == "soft"
    assert intent["visual_support_status"] == "unknown" and metadata["realization_review"] == "unreviewed"
    assert metadata["approval_status"] == "GENERATING"
    assert metadata["dialogue_assignment"][4]["speaker"] == "皇帝"
    ai.resolve_canonical_dialogue_timeline(shot)
    assert len(allocations) == (0 if official else 1)
    enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_09_frozen_h3_prompt_and_context_are_byte_identical(monkeypatch):
    data = frozen()
    plan = data["plan"]
    shot = SimpleNamespace(**data["shot"], video_director_plan=json.dumps(plan, ensure_ascii=False))
    context = _semantic_clip_prompt_context(plan, data["metadata"])
    context["clip"].update(ai.build_execution_intent_metadata(plan["dialogue_timeline_source"], context["clip"]))
    captured = {}
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": data["llm_response"]}
    monkeypatch.setattr(ai, "LLMService", FakeLLM)
    monkeypatch.setattr(ai, "get_visual_prop_names", lambda db, nid, props: props)
    template = (Path(__file__).parents[1] / "prompt_templates/13_MiniMax_H3_MultiKeyframe_VideoPrompt_V1.txt").read_text()
    monkeypatch.setattr(ai, "resolve_prompt_template", lambda *args: SimpleNamespace(template=template, name="frozen #13"))
    prompt = await ai.build_h3_video_prompt(db=SimpleNamespace(commit=lambda: None),
        novel=SimpleNamespace(id="bfc54b7d-04da-43e8-9e11-ff9a6032de5e"), shot=shot,
        selected_mode="MULTI_KEYFRAME", clip=context["clip"], workflow_capability={}, workflow_type="multi_reference_video",
        workflow_name="frozen workflow", start_image_url=None, keyframes=context["keyframes"],
        transitions=context["transitions"], clip_dialogues=context["clip_dialogues"], reference_images=[],
        video_reference_manifest=data["metadata"]["video_reference_manifest"])
    before = (FIXTURES / "video_director_phase_a_prompt.txt").read_text()
    assert prompt.encode() == before.encode(), "".join(difflib.unified_diff(before.splitlines(True), prompt.splitlines(True), fromfile="before", tofile="after"))
    encoded = json.dumps(captured, ensure_ascii=False, sort_keys=True, indent=2).encode()
    assert hashlib.sha256(encoded).hexdigest() == data["baseline_context_sha256"]


def test_10_attention_and_existing_prompt_cache_ignore_new_metadata():
    data = frozen()
    plan, manifest = data["plan"], data["metadata"]["video_reference_manifest"]
    clip = plan["clip_plan"][0]
    original_attention = copy.deepcopy(plan["visual_attention"])
    attention = ai.prepare_clip_visual_attention(plan, clip, json.loads(data["shot"]["characters"]), manifest=manifest)
    prompt = (FIXTURES / "video_director_phase_a_prompt.txt").read_text()
    clip.update(prompt_text=prompt, prompt_projection=prompt_projection_metadata(attention, prompt))
    assert get_semantic_clip_prompt(plan, clip, manifest) == prompt
    clip.update(ai.build_execution_intent_metadata(plan["dialogue_timeline_source"], clip))
    after = ai.prepare_clip_visual_attention(plan, clip, json.loads(data["shot"]["characters"]), manifest=manifest)
    assert after == attention
    assert plan["visual_attention"] == original_attention
    assert get_semantic_clip_prompt(plan, clip, manifest) == prompt


def test_11_all_prompt_templates_and_workflows_match_preflight_hashes():
    root = Path(__file__).parents[2]
    for name, expected in frozen()["frozen_files"].items():
        if name == "backend/prompt_templates/10A_NovelFlow_ClipExecutionPlanner_V1.txt":
            continue  # B2 authorizes #10A changes; its contract/sync tests protect the new source.
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name


def test_12_formal_d1_through_d6_canonical_fixture_is_protected():
    data = frozen()
    shot = SimpleNamespace(**data["shot"], video_director_plan=json.dumps(data["plan"], ensure_ascii=False))
    timeline, _ = ai.resolve_canonical_dialogue_timeline(shot)
    expected = [("骗子1", "尊贵的陛下。", 1, 2.25), ("骗子2", "我们终于有幸见到您了。", 2.45, 4.95),
                ("皇帝", "听说你们会织一种特别的布？", 5.15, 8.15), ("骗子1", "是的，陛下。", 8.35, 9.35),
                ("皇帝", "它有多漂亮？", 9.55, 10.8), ("骗子2", "它轻得像清晨的雾。", 11, 13)]
    assert [(e["speaker"], e["text"], e["start_time"], e["end_time"]) for e in timeline[:6]] == expected
    assert [e["id"] for e in timeline[:6]] == [f"D{i}" for i in range(1, 7)]
    assert shot.id == "58fa07ca-9cbf-44ba-9aca-57beb79a395c"


def test_no_dialogue_story_fact_and_explicit_event_ids_remain_hard():
    shot, plan = small_shot(False)
    shot.dialogues = "[]"
    assert ai.resolve_canonical_dialogue_timeline(shot, plan)[0] == []
    plan["dialogue_timeline_source"] = [{"id": "D1", "text": "invented", "speaker": "皇帝", "start_time": 1, "end_time": 2}]
    with pytest.raises(ValueError): ai.resolve_canonical_dialogue_timeline(shot, plan)
    shot.dialogues = json.dumps([{"id": "custom-event", "order": 7, "character_name": "皇帝", "text": "  exact whitespace。  "}])
    timeline, _ = ai.resolve_canonical_dialogue_timeline(shot, {})
    assert timeline[0]["id"] == "custom-event" and timeline[0]["text"] == "  exact whitespace。  "
