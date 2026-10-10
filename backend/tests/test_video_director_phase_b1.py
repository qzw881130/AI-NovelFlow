"""B1 extracts planned metadata only; real networks, media, and services are unused."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.task import Task
from app.services import clip_planner as planner, video_director_ai as ai
from app.services.shot_video_service import _semantic_clip_prompt_context, get_semantic_clip_prompt
from app.services.visual_attention import prompt_projection_metadata
import test_video_director_phase_a as phase_a

FIXTURES = Path(__file__).parent / "fixtures"
EMPEROR = "bbfa698b-e38e-40db-8cc9-ae0ab381fc4f"
OTHER = "e5744860-fb0a-4fb1-87a7-3abeb013878f"
CATALOG = [{"character_id": EMPEROR, "character_name": "皇帝"}, {"character_id": OTHER, "character_name": "骗子1"}]


def fixture():
    return json.loads((FIXTURES / "video_director_phase_b1.json").read_text())


def window(start, end, primary=None, background=None, **extra):
    return {"start_time_seconds": start, "end_time_seconds": end,
            "primary_subjects": [EMPEROR] if primary is None else primary,
            "background_motion_subjects": background or [], **extra}


def inputs(*, speaker="皇帝", event_start=1, event_end=2, clip_start=0, clip_end=10, windows=None, states=None):
    timeline = [{"id": "D5", "speaker": speaker, "text": "它有多漂亮？", "start_time": event_start, "end_time": event_end}]
    clip = {"clip_index": 1, "start_time": clip_start, "end_time": clip_end, "visual_state_indexes": [1, 2, 3],
            "temporal_anchor_ids": [], "dialogue_assignment": [{"dialogue_id": "D5", "segment_index": 1,
                "speaker": "stale speaker", "text": "stale text", "start_time": 0, "end_time": 1}]}
    plan = {"visual_attention": {"version": 1, "time_base": "SHOT_SECONDS", "character_catalog": copy.deepcopy(CATALOG),
                                  "windows": windows if windows is not None else [window(clip_start, clip_end)]},
            "keyframes": states if states is not None else [{"index": 1, "time_seconds": clip_start, "role": "START"}]}
    return timeline, clip, plan


def event_evidence(args, **kwargs):
    return ai.build_dialogue_visual_support_evidence(*args, **kwargs)["events"][0]


def formal_evidence():
    data, b1 = phase_a.frozen(), fixture()
    plan, clip = data["plan"], data["plan"]["clip_plan"][0]
    return ai.build_dialogue_visual_support_evidence(plan["dialogue_timeline_source"], clip, plan,
        reference_manifest=b1["clip1_manifest"], temporal_anchors=b1["clip4_temporal_manifest"]["anchors"],
        subject_bindings=b1["clip1_subject_bindings"])


def test_b1_01_canonical_and_assignment_are_immutable_and_join_is_deterministic():
    data, b1 = phase_a.frozen(), fixture()
    args = (data["plan"]["dialogue_timeline_source"], data["plan"]["clip_plan"][0], data["plan"])
    kwargs = dict(reference_manifest=b1["clip1_manifest"], subject_bindings=b1["clip1_subject_bindings"])
    before = copy.deepcopy((args, kwargs))
    first = ai.build_dialogue_visual_support_evidence(*args, **kwargs)
    second = ai.build_dialogue_visual_support_evidence(*args, **kwargs)
    assert first == second and (args, kwargs) == before
    assert json.dumps(first, allow_nan=False, sort_keys=True) == json.dumps(second, allow_nan=False, sort_keys=True)
    assert [e["dialogue_id"] for e in first["events"]] == [f"D{i}" for i in range(1, 7)]
    d5 = args[0][4]
    assert (d5["speaker"], d5["text"], d5["start_time"], d5["end_time"]) == ("皇帝", "它有多漂亮？", 9.55, 10.8)
    # Evidence references L1 identity; it contains no alternate text/speaker/timeline owner.
    assert all("speaker" not in e and "text" not in e and "canonical_window" not in e for e in first["events"])


@pytest.mark.parametrize(("roles", "primary", "background", "handoff"), [
    (["primary"], [EMPEROR], [], None),
    (["background_motion"], [OTHER], [EMPEROR], None),
    (["primary", "handoff_participant"], [EMPEROR, OTHER], [], {"from": [OTHER], "to": [EMPEROR]}),
    (["not_listed"], [OTHER], [], None),
])
def test_b1_02_attention_uses_uuid_roles(roles, primary, background, handoff):
    extra = {"handoff": handoff} if handoff else {}
    result = event_evidence(inputs(windows=[window(0, 10, primary, background, **extra)]))
    assert result["resolved_character"]["character_id"] == EMPEROR
    assert result["attention"]["overlaps"][0]["roles"] == roles
    assert result["attention"]["handoff_overlap"] is bool(handoff)
    assert result["speaker_visibility"] == "unknown"


@pytest.mark.parametrize("damage", ["missing_speaker", "ambiguous_catalog", "name_only_role"])
def test_b1_02_unresolved_does_not_guess_from_display_text(damage):
    args = inputs(speaker="未知皇帝" if damage == "missing_speaker" else "皇帝")
    if damage == "ambiguous_catalog":
        args[2]["visual_attention"]["character_catalog"].append({"character_id": OTHER, "character_name": "皇帝"})
    elif damage == "name_only_role":
        args[2]["visual_attention"]["windows"][0]["primary_subjects"] = ["皇帝"]
    result = event_evidence(args)
    assert result["resolved_character"]["status"] == "unresolved"
    assert result["resolved_character"]["character_id"] is None
    for overlap in result["attention"]["overlaps"]:
        assert overlap["roles"] == ["unresolved"]
    assert result["identity_reference"]["available"] == "unknown"


def test_b1_03_multiple_windows_partial_coverage_and_uncovered_interval():
    result = event_evidence(inputs(event_start=1, event_end=5, windows=[window(0, 2), window(4, 10)]))
    attention = result["attention"]
    assert [o["interval"] for o in attention["overlaps"]] == [{"start": 1, "end": 2}, {"start": 4, "end": 5}]
    assert attention["coverage_duration"] == 2 and attention["coverage_ratio"] == 0.5
    assert attention["uncovered_intervals"] == [{"start": 2, "end": 4}]


def test_b1_03_nonzero_clip_origin_and_touching_windows():
    args = inputs(event_start=35, event_end=36.2, clip_start=30, clip_end=45,
                  windows=[window(30, 35, [OTHER]), window(35, 36), window(36, 37)])
    before = copy.deepcopy(args)
    result = event_evidence(args)
    assert [o["interval"] for o in result["attention"]["overlaps"]] == [{"start": 5, "end": 6}, {"start": 6, "end": 6.2}]
    assert result["attention"]["coverage_duration"] == 1.2 and result["attention"]["coverage_ratio"] == 1
    assert result["attention"]["uncovered_intervals"] == []
    assert args == before


@pytest.mark.parametrize("raw", [None, {"version": 1, "time_base": "SHOT_SECONDS", "windows": "broken"}])
def test_b1_03_missing_or_invalid_attention_coverage_is_unknown(raw):
    args = inputs()
    args[2]["visual_attention"] = raw
    result = event_evidence(args)["attention"]
    assert result["coverage_duration"] is None and result["coverage_ratio"] is None
    assert result["overlaps"] == []


@pytest.mark.parametrize(("members", "expected"), [(["皇帝"], "present"), (["骗子1"], "absent_from_planned_membership"),
                                                    (None, "unknown"), ([], "absent_from_planned_membership")])
def test_b1_04_structured_planned_membership(members, expected):
    state = {"index": 2, "time_seconds": 1.5}
    if members is not None: state["characters"] = members
    result = event_evidence(inputs(states=[state]))
    record = result["visual_states"]["states"][0]
    assert record["planned_speaker_membership"] == expected
    assert result["speaker_visibility"] == result["mouth_readability"] == "unknown"


@pytest.mark.parametrize(("description", "expected"), [("Characters:\n- 皇帝: seated", "present"),
                                                         ("The emperor is probably visible.", "unknown")])
def test_b1_04_reuses_existing_characters_block_parser_without_prose_inference(description, expected):
    result = event_evidence(inputs(states=[{"index": 1, "time_seconds": 0, "description": description}]))
    assert result["visual_states"]["states"][0]["planned_speaker_membership"] == expected


def test_b1_04_before_inside_after_and_nearest_are_point_associations():
    states = [{"index": i, "time_seconds": t} for i, t in enumerate([0, 1.5, 3], 1)]
    result = event_evidence(inputs(states=states))["visual_states"]
    assert (result["before_state_id"], result["inside_state_ids"], result["after_state_id"], result["nearest_state_ids"]) == ("KF1", ["KF2"], "KF3", ["KF2"])


def test_b1_05_ordinary_anchor_type_slots_states_and_relationships():
    d5 = formal_evidence()["events"][4]
    anchors = d5["anchors"]["ordinary_visual"]
    assert [a["reference_type"] for a in anchors] == ["DIRECTOR_VISUAL_ANCHOR"] * 3
    assert [a["source_state_id"] for a in anchors] == ["KF1", "KF2", "KF3"]
    assert [a["time_relationship"] for a in anchors] == ["before", "before", "after"]
    assert [a["nearest"] for a in anchors] == [False, False, True]
    assert d5["visual_states"]["nearest_state_ids"] == ["KF3"]


def test_b1_06_real_clip4_temporal_anchor_preserves_identity_type_and_local_time():
    data, b1 = phase_a.frozen(), fixture()
    clip, anchors = b1["clip4"], b1["clip4_temporal_manifest"]["anchors"]
    before = copy.deepcopy(anchors)
    evidence = ai.build_dialogue_visual_support_evidence(data["plan"]["dialogue_timeline_source"], clip, data["plan"], temporal_anchors=anchors)
    assert evidence["events"]
    for event in evidence["events"]:
        record = event["anchors"]["temporal"][0]
        assert (record["reference_id"], record["reference_type"], record["source_state_id"]) == ("clip-4-KF6", "TEMPORAL_ANCHOR", "KF6")
        canonical = next(e for e in data["plan"]["dialogue_timeline_source"] if e["id"] == event["dialogue_id"])
        a = round(max(clip["start_time"], canonical["start_time"]) - clip["start_time"], 2)
        b = round(min(clip["end_time"], canonical["end_time"]) - clip["start_time"], 2)
        assert record["time_relationship"] == ("before" if 12.65 < a else "after" if 12.65 > b else "inside")
    assert anchors == before


def test_b1_07_clip1_no_temporal_anchor_does_not_import_clip4_or_reclassify_kfs():
    evidence = formal_evidence()
    assert len(evidence["events"]) == 6
    for event in evidence["events"]:
        assert event["anchors"]["temporal"] == []
        assert len(event["anchors"]["ordinary_visual"]) == 3
        assert {a["reference_type"] for a in event["anchors"]["ordinary_visual"]} == {"DIRECTOR_VISUAL_ANCHOR"}


@pytest.mark.parametrize(("manifest", "expected"), [
    ({"version": 1, "references": [{"slot": 1, "kind": "CHARACTER_IDENTITY", "source_id": EMPEROR, "source_name": "renamed display label"}]}, True),
    ({"version": 1, "references": []}, False),
    (None, "unknown"), ({"references": []}, "unknown"),
    ({"version": 1, "references": [{"slot": 1, "kind": "CHARACTER_IDENTITY", "source_name": "皇帝"}]}, "unknown"),
    ({"version": 1, "references": [{"slot": 3, "kind": "CHARACTER_IDENTITY", "source_id": EMPEROR}]}, "unknown"),
])
def test_b1_08_identity_reference_true_false_unknown_and_uuid_join(manifest, expected):
    result = event_evidence(inputs(), reference_manifest=manifest)
    assert result["identity_reference"]["available"] == expected
    assert result["face_readability"] == result["speaker_visibility"] == "unknown"


def test_b1_09_no_truth_inflation_or_scene_prop_dialogue_attachment():
    evidence = formal_evidence()
    assert evidence["reference_summary"]["manifest_status"] == "complete"
    assert [ref["reference_type"] for ref in evidence["reference_summary"]["scene_prop_references"]] == ["SCENE", "PROP"]
    for event in evidence["events"]:
        assert event["identity_reference"]["available"] is True
        assert all(event[key] == "unknown" for key in ["speaker_visibility", "face_readability", "mouth_readability", "competing_face_salience"])
        assert "score" not in json.dumps(event) and "confidence" not in json.dumps(event)
        assert "supports_scene" not in event and "supports_prop" not in event
    assert evidence["events"][4]["resolved_character"]["subject"] == "<Subject 1>"


def test_b1_10_old_phase_a_clip_task_read_without_backfill_or_approval_changes(db_session):
    data = phase_a.frozen()
    clip = data["plan"]["clip_plan"][0]
    phase_a_meta = ai.build_execution_intent_metadata(data["plan"]["dialogue_timeline_source"], clip)
    task = Task(id="b1-legacy-task", type="shot_video", name="legacy", status="completed",
                metadata_json=json.dumps({**phase_a_meta, "approval_status": "APPROVED"}))
    db_session.add(task); db_session.commit()
    before = task.metadata_json
    semantics = ai.read_execution_semantics(json.loads(task.metadata_json))
    assert semantics["visual_support_evidence"] == {"version": "legacy", "basis": "unknown", "status": "unknown", "events": []}
    assert semantics["execution_intent"] == phase_a_meta["execution_intent"]
    assert semantics["realization_review"] == "unreviewed"
    assert task.metadata_json == before and not db_session.dirty
    assert json.loads(task.metadata_json)["approval_status"] == "APPROVED"
    assert "visual_support_evidence" not in clip


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["planner", "multiclip_planner"])
async def test_b1_11_planner_payload_decisions_and_phase_a_metadata_equal_frozen_baseline(monkeypatch, variant):
    data = fixture()[variant]
    shot, calls, anchors = SimpleNamespace(**data["shot"]), [], []
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "content": json.dumps(data["response"], ensure_ascii=False)}
    monkeypatch.setattr(planner, "LLMService", FakeLLM)
    monkeypatch.setattr(planner, "PromptTemplateService", lambda db: SimpleNamespace(
        get_default_system_template=lambda name: SimpleNamespace(template="frozen #10A", name="fixture")))
    clips, validation = await planner.plan_clips(None, SimpleNamespace(id="novel"), shot, anchors)
    original_calls = copy.deepcopy(calls)
    for call in original_calls:
        payload = json.loads(call["user_content"])
        assert payload.pop("dialogue_visual_planning_context")["phase"] == "PRE_PLANNING"
        call["user_content"] = json.dumps(payload, ensure_ascii=False, indent=2)
    # B2 authorizes this one input augmentation; every prior input remains identical.
    assert json.dumps(original_calls, ensure_ascii=False, sort_keys=True) == json.dumps(data["calls"], ensure_ascii=False, sort_keys=True)
    assert [{k: v for k, v in clip.items() if k != "visual_support_evidence"} for clip in clips] == data["clips"]
    assert validation == data["validation"] and anchors == data["temporal_anchors"]
    assert all(clip["visual_support_evidence"]["basis"] == "PLANNED_METADATA" for clip in clips)
    assert json.loads(shot.video_director_plan) == json.loads(data["shot"]["video_director_plan"])
    if variant == "multiclip_planner":
        assert [c["capability"] for c in clips] == ["GENERATE", "TEMPORAL_EXTEND"]
        assert clips[1]["visual_support_evidence"]["events"][0]["anchors"]["temporal"][0]["reference_id"] == "clip-2-KF3"


@pytest.mark.asyncio
async def test_b1_12_h3_prompt_llm_input_subject_picture_attention_dialogue_byte_identical(monkeypatch):
    # Reuse the Phase A golden compiler assertion, with B1 actually attached to its input Clip.
    data = phase_a.frozen()
    clip = data["plan"]["clip_plan"][0]
    clip["visual_support_evidence"] = formal_evidence()
    original_attention = copy.deepcopy(data["plan"]["visual_attention"])
    monkeypatch.setattr(phase_a, "frozen", lambda: copy.deepcopy(data))
    await phase_a.test_09_frozen_h3_prompt_and_context_are_byte_identical(monkeypatch)
    assert data["plan"]["visual_attention"] == original_attention


def test_b1_13_b1_only_metadata_does_not_stale_an_existing_valid_prompt():
    data = phase_a.frozen()
    plan, clip, manifest = data["plan"], data["plan"]["clip_plan"][0], fixture()["clip1_manifest"]
    attention = ai.prepare_clip_visual_attention(plan, clip, json.loads(data["shot"]["characters"]), manifest=manifest)
    prompt = (FIXTURES / "video_director_phase_a_prompt.txt").read_text()
    clip.update(prompt_text=prompt, prompt_projection=prompt_projection_metadata(attention, prompt))
    assert get_semantic_clip_prompt(plan, clip, manifest) == prompt
    clip["visual_support_evidence"] = formal_evidence()
    assert get_semantic_clip_prompt(plan, clip, manifest) == prompt
    assert ai.prepare_clip_visual_attention(plan, clip, json.loads(data["shot"]["characters"]), manifest=manifest) == attention


def test_b1_14_frozen_templates_workflows_and_formal_canonical_fixture():
    data = phase_a.frozen()
    root = Path(__file__).parents[2]
    for name, expected in data["frozen_files"].items():
        if name == "backend/prompt_templates/10A_NovelFlow_ClipExecutionPlanner_V1.txt":
            continue  # B2 template contract/sync tests now own this authorized change.
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    before = copy.deepcopy(data)
    formal_evidence()
    assert data == before
    assert fixture()["formal_task_id"] == "9ccf4264-be19-4489-8c4c-8e8a470c6ad5"


@pytest.mark.asyncio
async def test_new_task_persists_optional_b1_evidence_in_memory_without_generation(db_session, monkeypatch):
    await phase_a.test_08_new_semantic_task_records_intent_without_executing(db_session, monkeypatch, True)
    task = db_session.query(Task).one()
    metadata = json.loads(task.metadata_json)
    assert metadata["visual_support_evidence"]["version"] == 1
    assert len(metadata["visual_support_evidence"]["events"]) == 6
    assert metadata["execution_intent"]["visual_support_status"] == "unknown"
    assert metadata["realization_review"] == "unreviewed"
    assert metadata["approval_status"] == "GENERATING"


def test_no_dialogue_fact_has_no_evidence_events():
    args = inputs()
    assert ai.build_dialogue_visual_support_evidence([], args[1], args[2])["events"] == []
