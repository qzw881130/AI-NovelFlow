"""B4 optional intent contracts, real deterministic consumers, fake LLMs and memory DBs."""
import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api import shots as api
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.repositories.task import TaskRepository
from app.repositories.shot_repository import ShotRepository
from app.services import video_director_ai as ai, shot_video_service as service
from app.services.clip_execution_compiler import compile_generate_clip, compile_extend_clip
from app.schemas.shot import PlanClipsRequest
import test_video_director_phase_a as phase_a
import test_video_director_phase_b1 as b1
import test_video_director_phase_b2 as b2

ROOT = Path(__file__).parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
PARTICIPATION = "SUPPORT_SPEAKER_PARTICIPATION"
SWINDLER = "e5744860-fb0a-4fb1-87a7-3abeb013878f"


def fixture():
    return json.loads((FIXTURES / "video_director_phase_b4.json").read_text())


def carrier(dialogue_id="D4", target=SWINDLER, intent=PARTICIPATION):
    event = {"dialogue_id": dialogue_id, "intent": intent}
    if intent != "PRESERVE_EXISTING":
        event["target_character_id"] = target
    return {"version": 1, "mode": "soft", "events": [event]}


def inputs(on=True):
    data = phase_a.frozen()
    clip = copy.deepcopy(fixture()["accepted_off"]["clips"][0])
    if on:
        clip["dialogue_visual_intent"] = carrier()
    data["plan"]["clip_plan"] = [clip]
    return data, clip


def validate(clip, data):
    return ai.validate_dialogue_visual_intent(clip, data["plan"]["dialogue_timeline_source"], data["plan"])


def compile_fixture(data, clip):
    shot = SimpleNamespace(**data["shot"], **fixture()["compiler_shot_media"],
                           video_director_plan=json.dumps(data["plan"], ensure_ascii=False))
    manifest = data["metadata"]["video_reference_manifest"]
    resources = {"references": [r for r in manifest["references"] if r["kind"] != "DIRECTOR_VISUAL_ANCHOR"],
                 "skipped_references": manifest["skipped_references"]}
    return compile_generate_clip(shot, data["plan"], clip, data["plan"]["clip_plan_revision"], resources)


async def planned_pair(monkeypatch):
    f = fixture()
    off = await b2.planned(monkeypatch, response=f["response_off"])
    on = await b2.planned(monkeypatch, response=f["response_on"])
    assert {"clips": off[0], "validation": off[1], "temporal_anchors": off[2]} == f["accepted_off"]
    assert off[3][0]["user_content"].encode() and hashlib.sha256(off[3][0]["user_content"].encode()).hexdigest() == f["user_content_sha256"]
    return off, on


def payload(captured):
    return json.loads(captured["user_content"].split("\n\n", 1)[1])


async def dry_pair(monkeypatch):
    off_data, off_clip = inputs(False)
    on_data, on_clip = inputs(True)
    off = await b2.h3_for_clips(monkeypatch, [off_clip])
    on = await b2.h3_for_clips(monkeypatch, [on_clip])
    return off, on, off_data, on_data


@pytest.mark.asyncio
async def test_b4_01_old_response_remains_identical_and_not_automatically_corrected(monkeypatch):
    off, _ = await planned_pair(monkeypatch)
    assert "dialogue_visual_intent" not in off[0][0]
    assert off[1]["passed"]


@pytest.mark.asyncio
async def test_b4_02_minimal_intent_parses_and_only_adds_optional_field(monkeypatch):
    off, on = await planned_pair(monkeypatch)
    new = copy.deepcopy(on[0][0])
    assert new.pop("dialogue_visual_intent") == carrier()
    assert new == off[0][0] and on[1:3] == off[1:3]


@pytest.mark.parametrize("damage,error", [
    ("enum", "ENUM_INVALID"), ("enum_structure", "ENUM_INVALID"), ("dialogue", "DIALOGUE_UNKNOWN"),
    ("uuid", "TARGET_UNRESOLVED"), ("unresolved_uuid", "TARGET_UNRESOLVED"),
    ("speaker", "SPEAKER_TARGET_MISMATCH"), ("duplicate", "DUPLICATE"),
    ("outside", "OUTSIDE_CLIP"), ("version", "SCHEMA_INVALID"),
    ("mode", "SCHEMA_INVALID"), ("timing", "EVENT_SCHEMA_INVALID"),
    ("truth", "EVENT_SCHEMA_INVALID"), ("free_prompt", "EVENT_SCHEMA_INVALID"),
    ("target_missing", "EVENT_SCHEMA_INVALID"), ("null", "SCHEMA_INVALID"),
])
def test_b4_03_to_07_contract_corruption_is_rejected(damage, error):
    data, clip = inputs()
    value = clip["dialogue_visual_intent"]; event = value["events"][0]
    if damage == "enum": event["intent"] = "CUT_TO_SPEAKER"
    elif damage == "enum_structure": event["intent"] = [PARTICIPATION]
    elif damage == "dialogue": event["dialogue_id"] = "NOT_CANONICAL"
    elif damage == "uuid": event["target_character_id"] = "骗子1"
    elif damage == "unresolved_uuid": event["target_character_id"] = "00000000-0000-0000-0000-000000000000"
    elif damage == "speaker": event["target_character_id"] = b1.EMPEROR
    elif damage == "duplicate": value["events"].append({"dialogue_id": "D4", "intent": "PRESERVE_EXISTING"})
    elif damage == "outside": event["dialogue_id"] = "D7"
    elif damage == "version": value["version"] = 2
    elif damage == "mode": value["mode"] = "hard"
    elif damage == "timing": event["start_time"] = 8.35
    elif damage == "truth": event["speaker_visible"] = True
    elif damage == "free_prompt": event["prompt"] = "cut to speaker"
    elif damage == "target_missing": del event["target_character_id"]
    elif damage == "null": clip["dialogue_visual_intent"] = None
    with pytest.raises(ValueError, match=error):
        validate(clip, data)


@pytest.mark.asyncio
async def test_invalid_planner_intent_is_rejected_before_acceptance(monkeypatch):
    response = fixture()["response_on"]
    response["clips"][0]["dialogue_visual_intent"]["events"][0]["target_character_id"] = b1.EMPEROR
    with pytest.raises(ValueError, match="SPEAKER_TARGET_MISMATCH"):
        await b2.planned(monkeypatch, response=response)


def test_b4_08_d4_uuid_and_canonical_window_are_valid_without_truth_inflation():
    data, clip = inputs(); before = copy.deepcopy(data)
    assert validate(clip, data) == carrier()
    assert data == before
    event = b2.event(b2.input_context(), "D4")
    assert event["attention"]["coverage_ratio"] == 1
    assert event["attention"]["overlaps"][0]["roles"] == ["not_listed"]
    assert event["canonical_reference"]["intended_window"] == {"start": 8.35, "end": 9.35}
    assert all(event[k] == "unknown" for k in ["speaker_visibility", "face_readability", "mouth_readability", "competing_face_salience"])


@pytest.mark.asyncio
async def test_b4_09_d5_positive_case_has_no_unnecessary_corrective_h3_entry(monkeypatch):
    _, on, _, _ = await dry_pair(monkeypatch)
    assert [e["dialogue_id"] for e in payload(on[1])["dialogue_visual_intents"]] == ["D4"]
    assert "D5" not in on[0].split("dialogue_visual_guidance:", 1)[1].split("visual_attention_timeline:", 1)[0]


@pytest.mark.asyncio
async def test_b4_10_d3_legitimate_handoff_is_byte_preserved(monkeypatch):
    off, on, _, _ = await dry_pair(monkeypatch)
    assert payload(off[1])["visual_attention_timeline"] == payload(on[1])["visual_attention_timeline"]
    assert off[0].split("visual_attention_timeline:", 1)[1] == on[0].split("visual_attention_timeline:", 1)[1]
    assert b2.event(b2.input_context(), "D3")["attention"]["handoff_overlap"]


@pytest.mark.parametrize("preserve_id", ["D3", "D5"])
def test_preserve_existing_is_accepted_but_has_no_effective_projection(preserve_id):
    data, clip = inputs()
    clip["dialogue_visual_intent"] = carrier(preserve_id, intent="PRESERVE_EXISTING")
    assert validate(clip, data)
    assert ai.executable_dialogue_visual_intents(clip, data["plan"]["dialogue_timeline_source"], data["plan"]) == []
    assert "dialogue_visual_intent" not in compile_fixture(data, clip)["execution_contract"]


def test_validator_does_not_delete_model_judgment_for_primary_support():
    data, clip = inputs()
    clip["dialogue_visual_intent"] = carrier("D5", b1.EMPEROR)
    assert validate(clip, data) == clip["dialogue_visual_intent"]
    assert ai.executable_dialogue_visual_intents(clip, data["plan"]["dialogue_timeline_source"], data["plan"])


def test_b4_11_reaction_fixture_keeps_listener_primary_and_speaker_background():
    timeline, clip, plan = b1.inputs(windows=[b1.window(0, 10, [SWINDLER], [b1.EMPEROR])])
    before = copy.deepcopy(plan)
    clip["dialogue_visual_intent"] = carrier("D5", b1.EMPEROR)
    result = ai.executable_dialogue_visual_intents(clip, timeline, plan)
    section = ai.render_dialogue_visual_guidance(result, ai.project_resolved_dialogue_timeline(timeline, clip, []),
                                                plan["visual_attention"]["character_catalog"], {"皇帝": "<Subject 1>"})
    assert "shared/reaction composition" in section and "existing reaction subject" in section
    assert "background participation" in section
    assert plan == before
    assert plan["visual_attention"]["windows"][0]["primary_subjects"] == [SWINDLER]


def test_b4_12_unknown_evidence_does_not_invent_uuid_subject_picture_or_truth():
    timeline, clip, plan = b1.inputs(speaker="Unknown speaker", states=[])
    plan["visual_attention"] = None
    assert ai.executable_dialogue_visual_intents(clip, timeline, plan) == []
    clip["dialogue_visual_intent"] = carrier("D5", b1.EMPEROR)
    with pytest.raises(ValueError, match="TARGET_UNRESOLVED"):
        ai.executable_dialogue_visual_intents(clip, timeline, plan)


@pytest.mark.asyncio
async def test_b4_13_no_dialogue_empty_optional_intent_is_byte_identical(monkeypatch):
    data, clip = inputs(False)
    data["shot"]["dialogues"] = "[]"; data["plan"]["dialogue_timeline_source"] = []
    data["metadata"]["dialogue_assignment"] = []; clip["dialogue_assignment"] = []
    with monkeypatch.context() as m:
        m.setattr(phase_a, "frozen", lambda: copy.deepcopy(data))
        off = await b2.h3_for_clips(m, [clip])
        clip["dialogue_visual_intent"] = {"version": 1, "mode": "soft", "events": []}
        on = await b2.h3_for_clips(m, [clip])
    assert off == on


@pytest.mark.asyncio
@pytest.mark.parametrize("keys", [
    ["dialogue_assignment"], ["start_time", "end_time", "planned_duration"],
    ["capability", "continuity_to_previous"],
    ["visual_state_indexes", "carry_in_state_index", "selected_temporal_target_ids", "early_composition_state_id", "inherited_start_composition", "temporal_anchor_ids"],
])
async def test_b4_14_to_19_canonical_boundary_capability_temporal_are_frozen(monkeypatch, keys):
    off, on = await planned_pair(monkeypatch)
    assert {k: off[0][0].get(k) for k in keys} == {k: on[0][0].get(k) for k in keys}
    if keys == ["dialogue_assignment"]:
        d4 = off[0][0]["dialogue_assignment"][3]
        assert (d4["speaker"], d4["text"], d4["start_time"], d4["end_time"]) == ("骗子1", "是的，陛下。", 8.35, 9.35)


def test_b4_20_attention_source_and_compiled_snapshot_are_identical():
    off_data, off_clip = inputs(False); on_data, on_clip = inputs()
    assert off_data["plan"]["visual_attention"] == on_data["plan"]["visual_attention"]
    off = compile_fixture(off_data, off_clip); on = compile_fixture(on_data, on_clip)
    assert off["execution_contract"]["visual_attention_snapshot"] == on["execution_contract"]["visual_attention_snapshot"]


def test_b4_21_ordinary_manifest_stays_nine_slots_with_three_dva_and_zero_temporal():
    off_data, off_clip = inputs(False); on_data, on_clip = inputs()
    off = compile_fixture(off_data, off_clip); on = compile_fixture(on_data, on_clip)
    assert off["video_reference_manifest"] == on["video_reference_manifest"]
    refs = on["video_reference_manifest"]["references"]
    assert len(refs) == 9 and [r["slot"] for r in refs] == list(range(1, 10))
    assert [r["source_keyframe_index"] for r in refs if r["kind"] == "DIRECTOR_VISUAL_ANCHOR"] == [1, 2, 3]
    assert on_clip["temporal_anchor_ids"] == []


@pytest.mark.asyncio
async def test_b4_22_existing_subject_picture_and_reference_bindings_are_identical(monkeypatch):
    off, on, _, _ = await dry_pair(monkeypatch)
    for key in ["reference_binding_contract", "physical_picture_manifest", "clip_visible_characters", "picture_mapping_contract"]:
        assert payload(off[1])[key] == payload(on[1])[key]


def test_b4_23_compiler_contract_and_task_context_carry_only_executable_events():
    data, clip = inputs()
    compiled = compile_fixture(data, clip)
    assert compiled["execution_contract"]["dialogue_visual_intent"] == carrier()
    metadata = {**data["metadata"], **compiled}
    data["plan"]["clip_plan"][0].pop("dialogue_visual_intent")
    context = service._semantic_clip_prompt_context(data["plan"], metadata)
    assert context["clip"]["dialogue_visual_intent"] == carrier()
    assert "text" not in json.dumps(carrier()) and "start_time" not in json.dumps(carrier())


@pytest.mark.asyncio
async def test_compiled_task_context_intent_reaches_actual_h3_call(monkeypatch):
    data, clip = inputs()
    compiled = compile_fixture(data, clip)
    data["metadata"].update(compiled)
    data["plan"]["clip_plan"][0].pop("dialogue_visual_intent")
    with monkeypatch.context() as m:
        m.setattr(phase_a, "frozen", lambda: copy.deepcopy(data))
        _, call = await b2.h3_for_clips(m, data["plan"]["clip_plan"])
    assert payload(call)["dialogue_visual_intents"] == carrier()["events"]


@pytest.mark.asyncio
async def test_b4_24_25_h3_whitelist_and_actual_llm_input_receive_minimal_intent(monkeypatch):
    off, on, _, _ = await dry_pair(monkeypatch)
    assert off[1] != on[1]
    assert payload(on[1])["dialogue_visual_intents"] == carrier()["events"]
    assert "dialogue_visual_intents" not in payload(off[1])
    assert b2.CONTEXT not in on[1]["user_content"] and "reason" not in payload(on[1])["clip"]


@pytest.mark.asyncio
async def test_b4_26_input_and_final_semantic_delta_are_only_the_d4_intent(monkeypatch):
    off, on, off_data, on_data = await dry_pair(monkeypatch)
    new = payload(on[1]); assert new.pop("dialogue_visual_intents") == carrier()["events"]
    assert new == payload(off[1])
    assert on[1]["system_prompt"] == off[1]["system_prompt"] + "\n\n" + ai.DIALOGUE_VISUAL_INTENT_RULE
    for key in off[1].keys() - {"system_prompt", "user_content"}:
        assert off[1][key] == on[1][key]
    section = service._dialogue_visual_guidance_for_clip(on_data["plan"], on_data["plan"]["clip_plan"][0])
    assert on[0].replace("\n\n" + section, "") == off[0]
    assert hashlib.sha256(off[0].encode()).hexdigest() == fixture()["h3_prompt_off_sha256"]
    assert hashlib.sha256(json.dumps(off[1], ensure_ascii=False, sort_keys=True, indent=2).encode()).hexdigest() == fixture()["h3_input_off_sha256"]


@pytest.mark.asyncio
async def test_b4_27_28_final_soft_semantics_support_shared_composition_without_camera_override(monkeypatch):
    _, on, _, _ = await dry_pair(monkeypatch)
    guidance = on[0].split("dialogue_visual_guidance:", 1)[1].split("visual_attention_timeline:", 1)[0]
    assert "D4 (8.35–9.35s, canonical Clip-local projection)" in guidance
    assert "<Subject 3>'s visual participation" in guidance
    assert "Preserve shared/reaction composition and the existing reaction subject" in guidance
    assert "attention handoffs, continuity and camera design" in guidance
    assert "no primary-subject, close-up, centering, exclusive-focus or camera-cut requirement" in guidance
    for forbidden in ["must be close-up", "must be centered", "must face camera", "camera cuts to speaker", "listener disappears", "sole visual focus"]:
        assert forbidden not in guidance


@pytest.mark.asyncio
async def test_b4_29_30_dialogue_authority_text_speaker_time_silence_are_byte_preserved(monkeypatch):
    off, on, _, _ = await dry_pair(monkeypatch)
    for key in ["dialogue_timeline_source", "dialogue_timeline_status", "silent_characters"]:
        assert payload(off[1])[key] == payload(on[1])[key]
    start = off[0].index("dialogue_timeline:")
    end = off[0].find("\n\n", start)
    assert off[0][start:end] == on[0][start:end]
    for event in payload(on[1])["dialogue_timeline_source"]:
        assert off[0].count(event["text"]) == on[0].count(event["text"])


@pytest.mark.asyncio
@pytest.mark.parametrize("route,owned", [("single", [1]), ("endpoint", [1, 3]), ("multi", [1, 2, 3])])
async def test_b4_31_to_33_all_h3_capabilities_consume_same_soft_contract(monkeypatch, route, owned):
    data, clip = inputs(); clip["visual_state_indexes"] = owned
    if route == "endpoint":
        data["plan"]["keyframes"][2]["role"] = "END"
    # Routing must use the real shared builder and actual capability template.
    calls = []
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "content": data["llm_response"]}
    monkeypatch.setattr(ai, "LLMService", FakeLLM)
    monkeypatch.setattr(ai, "get_visual_prop_names", lambda db, nid, props: props)
    files = {"h3_single_frame_prompt": "11_MiniMax_H3_SingleFrame_VideoPrompt_V1.txt",
             "h3_first_last_frame_prompt": "12_MiniMax_H3_FirstLastFrame_VideoPrompt_V1.txt",
             "h3_multi_keyframe_prompt": "13_MiniMax_H3_MultiKeyframe_VideoPrompt_V1.txt"}
    monkeypatch.setattr(ai, "resolve_prompt_template", lambda db, novel, attr, kind: SimpleNamespace(
        name=kind, template=(ROOT / "backend/prompt_templates" / files[kind]).read_text()))
    shot = SimpleNamespace(**data["shot"], video_director_plan=json.dumps(data["plan"]))
    prompt = await ai.build_h3_video_prompt(
        db=SimpleNamespace(commit=lambda: None), novel=SimpleNamespace(id="novel"), shot=shot,
        selected_mode="MULTI_KEYFRAME", clip=clip, workflow_capability={}, workflow_type="multi_reference_video",
        workflow_name="frozen", start_image_url=None, keyframes=data["plan"]["keyframes"],
        transitions=data["plan"]["transitions"], clip_dialogues=[], reference_images=[],
        video_reference_manifest=data["metadata"]["video_reference_manifest"])
    assert payload(calls[0])["visual_control_route"] == route
    assert payload(calls[0])["dialogue_visual_intents"] == carrier()["events"]
    assert "dialogue_visual_guidance:" in prompt and "shared/reaction composition" in prompt


def test_b4_34_35_legacy_task_approved_remains_unchanged(db_session):
    phase_a.test_07_old_approved_task_remains_approved_and_unreviewed(db_session)
    task = db_session.get(Task, "legacy-approved"); before = task.metadata_json
    data, clip = inputs(False)
    assert validate(clip, data) is None
    assert "dialogue_visual_intent" not in compile_fixture(data, clip)["execution_contract"]
    assert task.metadata_json == before and not db_session.dirty


@pytest.mark.asyncio
async def test_b4_36_cache_on_off_isolation_both_directions_and_hits(monkeypatch):
    off, on, off_data, on_data = await dry_pair(monkeypatch)
    off_clip = off_data["plan"]["clip_plan"][0]; on_clip = on_data["plan"]["clip_plan"][0]
    manifest = off_data["metadata"]["video_reference_manifest"]
    attention = ai.prepare_clip_visual_attention(off_data["plan"], off_clip, json.loads(off_data["shot"]["characters"]), manifest=manifest)
    old_cache = service.clip_prompt_projection_metadata(off_data["plan"], off_clip, attention, off[0])
    new_cache = service.clip_prompt_projection_metadata(on_data["plan"], on_clip, attention, on[0])
    assert "dialogue_visual_intent_sha256" not in old_cache
    assert "dialogue_visual_intent_sha256" in new_cache
    assert service.reusable_clip_prompt(off_data["plan"], off_clip, off[0], attention, old_cache)
    assert service.reusable_clip_prompt(on_data["plan"], on_clip, on[0], attention, new_cache)
    assert not service.reusable_clip_prompt(on_data["plan"], on_clip, off[0], attention, old_cache)
    assert not service.reusable_clip_prompt(off_data["plan"], off_clip, on[0], attention, new_cache)
    on_clip.update(prompt_text=off[0], prompt_projection=old_cache)
    assert service.get_semantic_clip_prompt(on_data["plan"], on_clip, manifest) == ""
    on_clip.update(prompt_text=on[0], prompt_projection=new_cache)
    assert service.get_semantic_clip_prompt(on_data["plan"], on_clip, manifest) == on[0]
    assert service.resolve_reusable_clip_prompt(on_data["plan"], on_clip,
        {"prompt_text": off[0], "prompt_projection": old_cache}, attention, skip_llm=True, clip_only=True, manifest=manifest) == on[0]
    on_clip["prompt_text"] = off[0]; on_clip["prompt_projection"] = old_cache
    assert service.resolve_reusable_clip_prompt(on_data["plan"], on_clip, {}, attention,
        skip_llm=True, clip_only=True, manifest=manifest) == ""


@pytest.mark.asyncio
async def test_effective_noop_uses_legacy_cache_without_changing_identity(monkeypatch):
    data, clip = inputs(False)
    prompt, _ = await b2.h3_for_clips(monkeypatch, [clip])
    attention = ai.prepare_clip_visual_attention(data["plan"], clip, json.loads(data["shot"]["characters"]), manifest=data["metadata"]["video_reference_manifest"])
    cache = service.clip_prompt_projection_metadata(data["plan"], clip, attention, prompt)
    clip["dialogue_visual_intent"] = carrier("D5", intent="PRESERVE_EXISTING")
    assert cache == service.clip_prompt_projection_metadata(data["plan"], clip, attention, prompt)
    assert service.reusable_clip_prompt(data["plan"], clip, prompt, attention, cache)


def test_b4_37_production_logical_rows_schema_and_templates_are_frozen_read_only():
    # SELECT-only corroboration of preflight; all application persistence tests use db_session.
    db = sqlite3.connect("file:" + str(ROOT / "backend/novelflow.db") + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON"); db.row_factory = sqlite3.Row
    try:
        def digest(value):
            return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        for table, expected in fixture()["frozen_database"].items():
            rows = [dict(r) for r in db.execute('SELECT * FROM "' + table + '" ORDER BY rowid')]
            if rows and "id" in rows[0]: rows.sort(key=lambda r: str(r["id"]))
            assert {"count": len(rows), "sha256": digest(rows)} == expected
        schema = [dict(r) for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
        assert digest(schema) == fixture()["schema_sha256"]
        text = db.execute("SELECT template FROM prompt_templates WHERE id=?", ("323f5869-05b2-44f2-a2fe-bf5936ac4096",)).fetchone()[0]
        assert hashlib.sha256(text.encode()).hexdigest() == fixture()["production_template_sha256"]
    finally:
        db.close()


def test_b4_38_workflows_and_08_11_12_13_templates_are_frozen():
    for path, expected in fixture()["frozen_files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected


@pytest.mark.asyncio
async def test_optional_clip_json_and_compiled_task_persist_in_memory_without_enqueue_work(db_session, monkeypatch):
    fake, plan = phase_a.small_shot()
    plan["visual_attention"] = phase_a.frozen()["plan"]["visual_attention"]
    novel = Novel(title="B4 isolated"); db_session.add(novel); db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="B4 isolated"); db_session.add(chapter); db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=3, duration=fake.duration, dialogues=fake.dialogues,
                characters=fake.characters, image_url="/api/files/fake-shot.png", video_director_plan=json.dumps(plan))
    db_session.add(shot); db_session.commit()
    b2.mock_planner(monkeypatch, fixture()["response_on"], [])
    monkeypatch.setattr(api, "get_canonical_execution_readiness", lambda *a: {"ready": True, "status": "NOT_EXECUTED"})
    monkeypatch.setattr(api, "_ensure_required_physical_images", lambda *a: None)
    result = await api.plan_shot_clips(novel.id, chapter.id, shot.id, PlanClipsRequest(force=True), db_session,
        SimpleNamespace(get_by_id=lambda *a: novel), ShotRepository(db_session))
    assert result["data"]["validation"]["passed"]
    db_session.expire_all(); plan = json.loads(shot.video_director_plan)
    assert plan["clip_plan"][0]["dialogue_visual_intent"] == carrier()
    workflow = SimpleNamespace(id="mock-workflow", name="frozen", type="multi_reference_video")
    monkeypatch.setattr(api, "WorkflowRepository", lambda db: SimpleNamespace(get_active_by_type=lambda kind: workflow))
    monkeypatch.setattr(api.TaskService, "validate_workflow_node_mapping", lambda *a: (True, ""))
    monkeypatch.setattr(api, "resolve_clip_reference_resources", lambda *a: {"references": [], "skipped_references": []})
    enqueue = MagicMock(); monkeypatch.setattr(api, "enqueue_shot_video_task", enqueue)
    result = await api.execute_semantic_clip(novel.id, chapter.id, shot.id, 1,
        api.SemanticClipGenerateRequest(clip_plan_revision=plan["clip_plan_revision"]), db_session,
        SimpleNamespace(get_by_id=lambda *a: novel), SimpleNamespace(get_by_id=lambda *a: chapter),
        TaskRepository(db_session), ShotRepository(db_session))
    metadata = json.loads(db_session.get(Task, result["data"]["taskId"]).metadata_json)
    assert metadata["execution_contract"]["dialogue_visual_intent"] == carrier()
    assert metadata["approval_status"] == "GENERATING" and metadata["realization_review"] == "unreviewed"
    assert json.loads(shot.video_director_plan)["dialogue_timeline_source"] == plan["dialogue_timeline_source"]
    enqueue.assert_called_once()


def test_prompt_preserves_b31_review_and_generic_minimal_contract():
    text = b2.TEMPLATE.read_text()
    for rule in ["Dialogue Visual Evidence Review (required planning step)", "Full coverage means the interval has attention windows",
                 "Planned membership in", "Primary plus handoff", "Actual", "reason", "non-executable",
                 "SUPPORT_SPEAKER_PARTICIPATION", "PRESERVE_EXISTING", "Missing field is legal",
                 "Do not produce an intent for every dialogue", "Speaker need not be primary"]:
        assert rule.lower() in text.lower()
    for specific in ["D3", "D4", "D5", "骗子1", "皇帝", "8.35", "9.35"]:
        assert specific not in text


def test_nonzero_clip_projects_only_canonical_interval_without_new_timing_owner():
    timeline, clip, plan = b1.inputs(event_start=35, event_end=36.2, clip_start=30, clip_end=45)
    clip["dialogue_visual_intent"] = carrier("D5", b1.EMPEROR)
    before = copy.deepcopy(timeline)
    section = ai.render_dialogue_visual_guidance(ai.executable_dialogue_visual_intents(clip, timeline, plan),
        ai.project_resolved_dialogue_timeline(timeline, clip, []), plan["visual_attention"]["character_catalog"], {"皇帝": "<Subject 1>"})
    assert "5.00–6.20s" in section and timeline == before
    assert "start_time" not in json.dumps(clip["dialogue_visual_intent"])


def test_extend_compiler_reuses_intent_without_changing_previous_av_contract():
    off_data, off_clip = inputs(False); on_data, on_clip = inputs()
    compiled = []
    previous = {"clip_index": 1, "clip_plan_revision": off_data["plan"]["clip_plan_revision"],
                "generated_by_task_id": "fake-approved-previous", "result_url": "/api/files/fake.mp4"}
    for data, clip in [(off_data, off_clip), (on_data, on_clip)]:
        clip.update(clip_index=2, capability="EXTEND", continuity_to_previous="CONTINUOUS", previous_clip_index=1)
        shot = SimpleNamespace(**data["shot"], **fixture()["compiler_shot_media"], video_director_plan=json.dumps(data["plan"]))
        compiled.append(compile_extend_clip(shot, data["plan"], clip, data["plan"]["clip_plan_revision"], previous))
    assert compiled[1]["execution_contract"].pop("dialogue_visual_intent") == carrier()
    assert compiled[0] == compiled[1]


@pytest.mark.asyncio
async def test_noop_d3_d5_does_not_change_h3_input_or_final_prompt(monkeypatch):
    data, clip = inputs(False)
    off = await b2.h3_for_clips(monkeypatch, [clip])
    clip["dialogue_visual_intent"] = {"version": 1, "mode": "soft", "events": [
        {"dialogue_id": did, "intent": "PRESERVE_EXISTING"} for did in ["D3", "D5"]]}
    on = await b2.h3_for_clips(monkeypatch, [clip])
    assert off == on


@pytest.mark.asyncio
async def test_missing_attention_still_isolates_b4_cache_and_keeps_unknown(monkeypatch):
    off, on, off_data, on_data = await dry_pair(monkeypatch)
    clip = on_data["plan"]["clip_plan"][0]
    absent = {"status": "ABSENT", "fingerprint": None}
    prompt = on[0].split("\n\nvisual_attention_timeline:", 1)[0]
    cache = service.clip_prompt_projection_metadata(on_data["plan"], clip, absent, prompt)
    assert service.reusable_clip_prompt(on_data["plan"], clip, prompt, absent, cache)
    assert not service.reusable_clip_prompt(on_data["plan"], clip, off[0].split("\n\nvisual_attention_timeline:", 1)[0], absent, cache)
    assert not service.reusable_clip_prompt(off_data["plan"], off_data["plan"]["clip_plan"][0], prompt, absent, cache)


@pytest.mark.asyncio
async def test_prompt_cache_write_can_be_read_with_b4_intent_and_rejects_off(monkeypatch):
    _, on, _, data = await dry_pair(monkeypatch)
    clip = data["plan"]["clip_plan"][0]; manifest = data["metadata"]["video_reference_manifest"]
    attention = ai.prepare_clip_visual_attention(data["plan"], clip, json.loads(data["shot"]["characters"]), manifest=manifest)
    shot = SimpleNamespace(video_director_plan=json.dumps(data["plan"]))
    db = SimpleNamespace(commit=MagicMock())
    service._update_clip_prompt(shot, clip, on[0], db, attention)
    plan = json.loads(shot.video_director_plan); persisted = plan["clip_plan"][0]
    assert service.get_semantic_clip_prompt(plan, persisted, manifest) == on[0]
    persisted.pop("dialogue_visual_intent")
    assert service.get_semantic_clip_prompt(plan, persisted, manifest) == ""
    assert db.commit.call_count == 1


@pytest.mark.asyncio
async def test_reaction_fixture_consumes_support_without_reassigning_primary_in_h3(monkeypatch):
    data, clip = inputs(); clip["dialogue_visual_intent"] = carrier("D5", b1.EMPEROR)
    data["plan"]["visual_attention"]["windows"] = [b1.window(0, 13.1, [SWINDLER], [b1.EMPEROR])]
    with monkeypatch.context() as m:
        m.setattr(phase_a, "frozen", lambda: copy.deepcopy(data))
        prompt, call = await b2.h3_for_clips(m, [clip])
    window = payload(call)["visual_attention_timeline"]["windows"][0]
    assert window["primary_subjects"] == [SWINDLER] and window["background_motion_subjects"] == [b1.EMPEROR]
    assert payload(call)["dialogue_visual_intents"] == carrier("D5", b1.EMPEROR)["events"]
    guidance = prompt.split("dialogue_visual_guidance:", 1)[1].split("visual_attention_timeline:", 1)[0]
    assert "<Subject 1>'s visual participation" in guidance and "existing reaction subject" in guidance
    assert "no primary-subject, close-up" in guidance
