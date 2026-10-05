"""Option B: semantic selection precedes physical image preparation (no real calls)."""
import json
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from app.services import clip_planner
from app.services.clip_execution_compiler import (
    TEMPORAL_DECISION_CONTRACT, get_canonical_execution_readiness,
)


def _states():
    return [
        {"index": 1, "role": "START", "time_seconds": 0, "timed_visual_target": False},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 6, "timed_visual_target": True},
        {"index": 3, "role": "INTERMEDIATE", "time_seconds": 8, "timed_visual_target": True},
        {"index": 4, "role": "INTERMEDIATE", "time_seconds": 10, "timed_visual_target": False},
        {"index": 5, "role": "END", "time_seconds": 12, "timed_visual_target": True},
    ]


def _clips(selected=None, continuity="CONTINUOUS", boundary=6):
    return [
        {"clip_index": 1, "start_time": 0, "end_time": boundary,
         "continuity_to_previous": "NONE", "selected_temporal_target_ids": [], "early_composition_state_id": None},
        {"clip_index": 2, "start_time": boundary, "end_time": 12,
         "continuity_to_previous": continuity, "selected_temporal_target_ids": selected or [],
         "early_composition_state_id": None,
         "previous_clip_index": 1 if continuity == "CONTINUOUS" else None,
         "reason": "planned movement needs prior ending; timed arrival evaluated separately"},
    ]


def _candidates(states=None):
    return [{**state, "visual_state_id": f"KF{state['index']}", "keyframe_index": state["index"],
             "image_available": bool(state.get("image_url")),
             "source": {"type": "KEYFRAME", "id": f"KF{state['index']}", "keyframe_index": state["index"]}}
            for state in states or _states()]


def _project(selected=None, continuity="CONTINUOUS", states=None):
    candidates, clips = _candidates(states), _clips(selected, continuity)
    clip_planner._project_clip_visual_states(clips, candidates)
    clip_planner._project_temporal_targets(clips, candidates, 12)
    return clips, clip_planner._build_temporal_anchors(clips, candidates)


@pytest.mark.parametrize("selected,capability", [([], "EXTEND"), (["KF3"], "TEMPORAL_EXTEND"),
                                               (["KF5", "KF3"], "TEMPORAL_EXTEND")])
def test_eligible_is_not_selected_and_program_derives_execution(selected, capability):
    clips, anchors = _project(selected)
    assert clips[1]["capability"] == capability
    assert clips[1]["selected_temporal_target_ids"] == sorted(selected, key=lambda item: int(item[2:]))
    assert len(anchors) == len(selected)


@pytest.mark.parametrize("selected,continuity", [(["KF4"], "CONTINUOUS"), (["KF2"], "CONTINUOUS"),
                                                (["KF1"], "CONTINUOUS"), (["KF3"], "CUT"),
                                                (["KF999"], "CONTINUOUS"), (["KF3", "KF3"], "CONTINUOUS")])
def test_illegal_selection_hard_fails(selected, continuity):
    with pytest.raises(ValueError, match="TEMPORAL_SELECTION_INVALID"):
        _project(selected, continuity)


def test_cut_empty_selection_has_no_temporal_anchors():
    clips, anchors = _project([], "CUT")
    assert clips[1]["capability"] == "GENERATE"
    assert clips[1]["requires_temporal_control"] is False
    assert anchors == []


def test_selection_list_is_mandatory_not_inferred_from_raw_capability():
    clips = _clips()
    del clips[1]["selected_temporal_target_ids"]
    clip_planner._project_clip_visual_states(clips, _candidates())
    with pytest.raises(ValueError, match="must be a list"):
        clip_planner._project_temporal_targets(clips, _candidates(), 12)


def test_raw_execution_fields_cannot_override_selection():
    clips = _clips(["KF3"])
    clips[1].update(capability="EXTEND", requires_temporal_control=False)
    clip_planner._project_clip_visual_states(clips, _candidates())
    clip_planner._project_temporal_targets(clips, _candidates(), 12)
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"
    assert clips[1]["requires_temporal_control"] is True


def test_empty_selection_overrides_raw_temporal_execution_claims():
    clips = _clips([])
    clips[1].update(capability="TEMPORAL_EXTEND", requires_temporal_control=True)
    clip_planner._project_clip_visual_states(clips, _candidates())
    clip_planner._project_temporal_targets(clips, _candidates(), 12)
    anchors = clip_planner._build_temporal_anchors(clips, _candidates())
    assert clips[1]["capability"] == "EXTEND"
    assert clips[1]["requires_temporal_control"] is False
    assert clips[1]["selected_temporal_target_ids"] == []
    assert clips[1]["temporal_anchor_ids"] == []
    assert anchors == []


def _composition_clips(selected=None, boundary=6):
    clips = _clips(selected, boundary=boundary)
    clips[1]["early_composition_state_id"] = None if "KF3" in (selected or []) else "KF4"
    return clips


async def _plan(monkeypatch, tmp_path, responses):
    image = tmp_path / "start.png"
    image.write_bytes(b"image")
    shot = SimpleNamespace(id="shot", chapter_id="chapter", duration=12, continuity_mode="NORMAL",
                           characters="[]", props="[]", scene="", dialogues="[]", image_url=str(image),
                           image_path=str(image), keyframes="[]", video_director_plan=json.dumps({
                               "canonical_visual_plan": True, "keyframes": [dict(state, image_url=str(image)) if state["index"] == 4 else state for state in _states()], "transitions": []}))
    calls = []
    class Template:
        def __init__(self, _db): pass
        def get_default_system_template(self, _name): return SimpleNamespace(template="planner", name="planner")
    class LLM:
        async def chat_completion(self, **kwargs):
            calls.append(json.loads(kwargs["user_content"]))
            return {"success": True, "content": json.dumps({"clips": deepcopy(responses[len(calls) - 1])})}
    monkeypatch.setattr(clip_planner, "PromptTemplateService", Template)
    monkeypatch.setattr(clip_planner, "LLMService", LLM)
    anchors = []
    clips, validation = await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, anchors)
    plan = json.loads(shot.video_director_plan)
    plan.update(clip_plan=clips, clip_plan_validation=validation, temporal_anchors=anchors, clip_plan_revision=1)
    return shot, plan, calls


@pytest.mark.asyncio
async def test_selected_missing_image_plan_valid_execution_blocked_then_normal_prep_ready(monkeypatch, tmp_path):
    shot, plan, calls = await _plan(monkeypatch, tmp_path, [_clips(["KF3"])])
    assert len(calls) == 1
    assert plan["clip_plan_validation"]["passed"] is True
    assert plan["clip_plan_validation"]["temporal_contract"] == TEMPORAL_DECISION_CONTRACT
    assert plan["clip_plan_validation"]["composition_contract"] == "EARLY_COMPOSITION_V2"
    readiness = get_canonical_execution_readiness(shot, plan)
    assert [item["visual_state_index"] for item in readiness["blocking_clips"]] == [3]
    assert readiness["code"] == "TEMPORAL_ANCHOR_UNAVAILABLE"
    from app.services.canonical_execution_invalidation import sync_temporal_anchor_state_image
    plan["keyframes"][2]["image_url"] = shot.image_url
    sync_temporal_anchor_state_image(plan, 3, shot.image_url, "image-task")
    assert get_canonical_execution_readiness(shot, plan)["ready"] is True
    assert not plan["keyframes"][4].get("image_url")  # unselected END is not required


@pytest.mark.asyncio
async def test_missing_eligible_unselected_images_do_not_block_plan_or_execution(monkeypatch, tmp_path):
    shot, plan, _ = await _plan(monkeypatch, tmp_path, [_composition_clips()])
    assert plan["clip_plan_validation"]["passed"] is True
    assert get_canonical_execution_readiness(shot, plan)["ready"] is True
    assert [a["source"]["id"] for a in plan["temporal_anchors"]] == ["KF4"]
    original = deepcopy(plan)
    del plan["clip_plan_validation"]["temporal_contract"]
    assert get_canonical_execution_readiness(shot, plan)["code"] == "TEMPORAL_CONTRACT_REPLAN_REQUIRED"
    assert plan["clip_plan"] == original["clip_plan"]  # no silent rewrite


@pytest.mark.asyncio
async def test_normalization_revalidation_includes_all_eligible_not_only_selected(monkeypatch, tmp_path):
    # 9/3 -> 8/4 duration repair changes ownership and eligible local positions.
    shot, plan, calls = await _plan(monkeypatch, tmp_path, [_composition_clips(["KF5"], boundary=9), _composition_clips(["KF5"], boundary=8)])
    assert len(calls) == 2
    constraints = calls[1]["continuity_revalidation"]["normalized_clips"]
    assert [item["visual_state_id"] for item in constraints[0]["eligible_temporal_targets"]] == ["KF2", "KF3"]
    assert constraints[1]["eligible_temporal_targets"][0]["clip_local_time"] == 4
    assert plan["clip_plan_validation"]["passed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("second", [_clips(["KF5"], boundary=9), _clips(["KF3"], boundary=8)])
async def test_second_drift_or_illegal_selection_hard_fails(monkeypatch, tmp_path, second):
    with pytest.raises(ValueError, match="CLIP_CONTINUITY_PREMISE_INVALIDATED|TEMPORAL_SELECTION_INVALID"):
        await _plan(monkeypatch, tmp_path, [_clips(["KF5"], boundary=9), second])


def test_export_distinguishes_eligible_selected_and_generate_grounding():
    from app.services.canonical_export import _state_records
    clips, anchors = _project(["KF3"])
    plan = {"keyframes": _states(), "clip_plan": clips, "temporal_anchors": anchors,
            "clip_plan_validation": {"temporal_contract": TEMPORAL_DECISION_CONTRACT}}
    shot = SimpleNamespace(image_url=None, image_path=None)
    with ZipFile(BytesIO(), "w") as archive:
        records = _state_records(archive, set(), "novel", shot, plan, "states", [])
    assert [(r["index"], r["timed_visual_target"], r["selected_temporal_target"], r["required"])
            for r in records] == [(1, False, False, True), (2, True, False, False),
                                 (3, True, True, True), (4, False, False, False), (5, True, False, False)]


def _db_fixture(db_session, tmp_path, *, marked=True):
    from app.models.novel import Novel, Chapter
    from app.models.shot import Shot
    from app.models.task import Task
    start = tmp_path / "main.png"
    start.write_bytes(b"main")
    old_artifact = tmp_path / "historical.mp4"
    old_artifact.write_bytes(b"historical")
    novel = Novel(id="temporal-novel", title="Temporal")
    chapter = Chapter(id="temporal-chapter", novel_id=novel.id, number=1, title="Chapter")
    clips, anchors = _project(["KF3"])
    clips[0].update(generated_by_task_id="historical-task", video_url=str(old_artifact), execution_status="APPROVED")
    plan = {"canonical_visual_plan": True, "keyframes": _states(), "clip_plan": clips,
            "clip_plan_revision": 7, "clip_plan_validation": {"passed": True}, "temporal_anchors": anchors}
    if marked:
        plan["clip_plan_validation"]["temporal_contract"] = TEMPORAL_DECISION_CONTRACT
        plan["clip_plan_validation"]["composition_contract"] = "EARLY_COMPOSITION_V2"
    shot = Shot(id="temporal-shot", chapter_id=chapter.id, index=1, duration=12, characters="[]", props="[]",
                dialogues="[]", image_url=str(start), video_url=str(old_artifact), video_director_plan=json.dumps(plan))
    task = Task(id="historical-task", type="shot_video", status="failed", name="Old task", novel_id=novel.id,
                chapter_id=chapter.id, shot_id=shot.id, workflow_id="unused", metadata_json=json.dumps({
                    "execution_scope": "CLIP", "clip_id": f"{shot.id}:clip:1", "clip_index": 1,
                    "clip_plan_revision": 7, "capability": "GENERATE", "planned_duration": 6,
                    "requested_duration": 6, "dialogue_assignment": []}))
    db_session.add_all([novel, chapter, shot, task])
    db_session.commit()
    return novel, chapter, shot, task, old_artifact


@pytest.mark.parametrize("marked,code", [(False, "TEMPORAL_CONTRACT_REPLAN_REQUIRED"), (True, "TEMPORAL_ANCHOR_UNAVAILABLE")])
def test_single_and_batch_preflight_reject_before_any_task_or_product_mutation(client, db_session, tmp_path, marked, code):
    from app.models.task import Task
    novel, chapter, shot, _, artifact = _db_fixture(db_session, tmp_path, marked=marked)
    old_plan, old_video, count = shot.video_director_plan, shot.video_url, db_session.query(Task).count()
    root = f"/api/novels/{novel.id}/chapters/{chapter.id}"
    response = client.post(f"{root}/shots/{shot.id}/video-director/clips/2/generate", json={"clip_plan_revision": 7})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    response = client.post(f"{root}/shot-videos/batch", json={"shot_ids": [shot.id], "force_rerun": True})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    db_session.refresh(shot)
    assert db_session.query(Task).count() == count
    assert shot.video_director_plan == old_plan and shot.video_url == old_video
    assert artifact.read_bytes() == b"historical"


def test_old_task_retry_does_not_upgrade_contract_or_clear_historical_result(db_session, tmp_path):
    from app.services.task_service import TaskService
    _, _, shot, task, artifact = _db_fixture(db_session, tmp_path, marked=False)
    before = task.metadata_json, shot.video_director_plan
    result = TaskService(db_session).retry_task(task.id)
    assert result["success"] is False and result["status_code"] == 409
    assert (task.metadata_json, shot.video_director_plan) == before
    assert task.status == "failed" and artifact.is_file()


def test_normal_replan_persists_marker_and_draft_anchors_without_real_calls(client, db_session, tmp_path, monkeypatch):
    from app.models.task import Task
    novel, chapter, shot, _, artifact = _db_fixture(db_session, tmp_path, marked=False)
    class LLM:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": _clips(["KF3"])})}
    monkeypatch.setattr(clip_planner, "LLMService", LLM)
    count = db_session.query(Task).count()
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/video-director/plan-clips", json={"force": True})
    assert response.status_code == 200, response.text
    db_session.refresh(shot)
    plan = json.loads(shot.video_director_plan)
    assert plan["clip_plan_validation"]["passed"] is True
    assert plan["clip_plan_validation"]["temporal_contract"] == TEMPORAL_DECISION_CONTRACT
    assert plan["clip_plan_revision"] == 8
    assert plan["clip_plan"][1]["selected_temporal_target_ids"] == ["KF3"]
    assert response.json()["data"]["execution_readiness"]["code"] == "TEMPORAL_ANCHOR_UNAVAILABLE"
    assert plan["temporal_anchors"][0]["image_url"] is None
    assert db_session.query(Task).count() == count and artifact.is_file()


def test_deleted_selected_physical_file_is_not_ready(tmp_path):
    image = tmp_path / "missing.png"
    states = _states()
    states[2]["image_url"] = str(image)
    clips, anchors = _project(["KF3"], states=states)
    plan = {"canonical_visual_plan": True, "keyframes": states, "clip_plan": clips, "temporal_anchors": anchors,
            "clip_plan_validation": {"passed": True, "temporal_contract": TEMPORAL_DECISION_CONTRACT, "composition_contract": "EARLY_COMPOSITION_V2"}}
    shot = SimpleNamespace(image_url="/main.png", image_path=None)
    assert get_canonical_execution_readiness(shot, plan)["code"] == "TEMPORAL_ANCHOR_UNAVAILABLE"


@pytest.mark.parametrize("marked", [False, True])
@pytest.mark.parametrize("endpoint", ["clip-plan", "generate-video"])
def test_canonical_legacy_execution_endpoints_reject_before_mutation(
    client, db_session, tmp_path, marked, endpoint,
):
    from app.models.novel import Chapter, Novel
    from app.models.shot import Shot
    from app.models.task import Task

    image = tmp_path / "main.png"
    image.write_bytes(b"main")
    artifact = tmp_path / "existing.mp4"
    artifact.write_bytes(b"existing-video")
    novel = Novel(id=f"cutoff-novel-{endpoint}-{marked}", title="Cutoff")
    chapter = Chapter(id=f"cutoff-chapter-{endpoint}-{marked}", novel_id=novel.id, number=1, title="Chapter")
    validation = {"passed": True}
    if marked:
        validation["temporal_contract"] = TEMPORAL_DECISION_CONTRACT
    plan = {
        "canonical_visual_plan": True,
        "clip_plan_revision": 4,
        "clip_plan_validation": validation,
        "keyframes": [{"index": 1, "role": "START", "time_seconds": 0, "timed_visual_target": False}],
        "clip_plan": [{"clip_index": 1, "start_time": 0, "end_time": 4, "planned_duration": 4,
                       "capability": "GENERATE", "continuity_to_previous": "NONE",
                       "selected_temporal_target_ids": [], "visual_state_indexes": [1],
                       "execution_status": "PLANNED"}],
    }
    shot = Shot(id=f"cutoff-shot-{endpoint}-{marked}", chapter_id=chapter.id, index=1, duration=4,
                image_url=str(image), image_path=str(image), video_url=str(artifact), video_status="completed",
                video_director_plan=json.dumps(plan))
    old_task = Task(id=f"cutoff-old-{endpoint}-{marked}", type="shot_video", status="failed", name="Old",
                    novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id, result_url=str(artifact))
    db_session.add_all([novel, chapter, shot, old_task])
    db_session.commit()
    before_plan = shot.video_director_plan
    before_count = db_session.query(Task).count()
    root = f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}"
    url = f"{root}/video-director/clip-plan/generate" if endpoint == "clip-plan" else f"{root}/generate-video"

    with (
        patch("app.repositories.workflow.WorkflowRepository.get_active_by_type") as workflow_lookup,
        patch("app.api.shots.file_storage.delete_shot_video") as delete_video,
        patch("app.api.shots.generate_shot_video_task") as legacy_enqueue,
        patch("app.services.shot_video_service.enqueue_shot_video_task") as clip_enqueue,
    ):
        response = client.post(url)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CANONICAL_SEMANTIC_LEGACY_EXECUTION_FORBIDDEN"
    assert "semantic Clip execution" in response.json()["detail"]["message"]
    db_session.refresh(shot)
    db_session.refresh(old_task)
    assert db_session.query(Task).count() == before_count
    assert shot.video_director_plan == before_plan
    assert shot.video_url == str(artifact) and shot.video_status == "completed"
    assert old_task.status == "failed" and old_task.result_url == str(artifact)
    assert artifact.read_bytes() == b"existing-video"
    workflow_lookup.assert_not_called()
    delete_video.assert_not_called()
    legacy_enqueue.assert_not_called()
    clip_enqueue.assert_not_called()


def test_noncanonical_legacy_clip_plan_endpoint_preserves_existing_behavior(
    client, db_session, tmp_path, monkeypatch,
):
    from app.models.novel import Chapter, Novel
    from app.models.shot import Shot
    from app.models.task import Task
    from app.models.workflow import Workflow
    from app.services import shot_video_service

    image = tmp_path / "legacy-main.png"
    image.write_bytes(b"legacy-main")
    novel = Novel(id="legacy-cutoff-novel", title="Legacy")
    chapter = Chapter(id="legacy-cutoff-chapter", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(id="legacy-cutoff-shot", chapter_id=chapter.id, index=1, duration=4,
                image_url=None, image_path=str(image), video_director_plan=json.dumps({
                    "clip_plan_revision": 1,
                    "clip_plan_validation": {"passed": True},
                    "clip_plan": [{"clip_index": 1, "planned_duration": 4, "capability": "SINGLE_FRAME",
                                   "execution_status": "PLANNED"}],
                }))
    workflow = Workflow(id="legacy-cutoff-workflow", name="Legacy video", type="video",
                        workflow_json="{}", is_active=True)
    db_session.add_all([novel, chapter, shot, workflow])
    db_session.commit()
    monkeypatch.setattr(shot_video_service, "enqueue_shot_video_task", lambda *args, **kwargs: None)
    before_count = db_session.query(Task).count()

    response = client.post(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/video-director/clip-plan/generate"
    )

    assert response.status_code == 200, response.text
    assert db_session.query(Task).count() == before_count + 1
    task = db_session.query(Task).filter(Task.id == response.json()["data"]["taskId"]).one()
    assert json.loads(task.metadata_json)["execution_scope"] == "CLIP"
