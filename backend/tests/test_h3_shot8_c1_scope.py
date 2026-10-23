"""Prose inference may warn only behind intact structured H3 authority."""
import copy
import json
from pathlib import Path

from app.services.h3_execution_optimizer import _auxiliary_wording_warnings
from app.services.h3_execution_optimizer import check_authority


SUBJECT = "<Subject 2>"
ACTOR = "群臣2"
FLOOR = f"canonical_floor_position_{SUBJECT}"
MARKER = f"{SUBJECT} — {ACTOR}: LOCAL_MOTION / SPATIALLY_ANCHORED; no explicit translational assignment."
CHECKS = {
    "canonical_visual_requirement_consistency": True,
    "reference_projection_consistent": True,
    "canonical_manifest_subject_consistent": True,
    "subject_binding": True, "subject_set": True,
    "invented_picture": True, "picture_presence": True,
    "anchor_required_outcomes_retained": True,
    "picture_binding_<Picture 4>": True,
    "native_dialogue_markup": True, "dialogue_ids_speakers_text_order": True,
    "stable_speaker_ids": True, "dialogue_duration_unchanged": True,
    "dialogue_timeline_matches_prompt_and_initial": True,
    "dialogue_inside_budget": True, "all_speaker_handoffs_consistent": True,
    "speaker_switch_camera_evidence": True,
    "duration_within_workflow_and_20s": True,
    "prompt_duration_matches_timeline": True,
    "duration_original_delta_changed": True,
    "h3_native_six_sections": True,
    "no_internal_execution_dsl": True,
}
AUTHORITY = {
    "subject_bindings": {SUBJECT: ACTOR},
    "anchor_policy": {"canonical_visual_sources": [{
        "id": "transition_1", "text": "群臣1与群臣2沿长廊并行前行。",
    }]},
}
EVIDENCE = {"entries": {"requirements.0.prompt": {"status": "RESOLVED"}}}


def _output(prompt="<Subject 2> walks beside <Subject 1>."):
    return {"optimized_prompt": prompt, "canonical_visual_requirements": [{
        "id": "CVR1", "source_id": "transition_1",
        "requirement": "Both ministers walk in parallel.",
        "prompt_excerpt": prompt,
    }]}


def test_wording_and_inferred_static_motion_are_recorded_as_warnings():
    failed = ["reference_authority_scope", "blocking_preservation_wording", FLOOR,
              "canonical_visual_requirement_trace"]
    warnings = _auxiliary_wording_warnings(failed, CHECKS, MARKER, _output(), AUTHORITY, EVIDENCE)
    assert {w["original_check"] for w in warnings} == set(failed) - {"canonical_visual_requirement_trace"}
    assert all(w["original_result"] is False for w in warnings)
    assert next(w for w in warnings if w["original_check"] == FLOOR)["canonical_transition_ids"] == ["transition_1"]


def test_core_picture_failure_or_unknown_source_prevents_demotion():
    checks = {**CHECKS, "picture_binding_<Picture 4>": False}
    assert not _auxiliary_wording_warnings([FLOOR], checks, MARKER, _output(), AUTHORITY, EVIDENCE)
    output = _output()
    output["canonical_visual_requirements"][0]["source_id"] = "transition_999"
    assert not _auxiliary_wording_warnings([FLOOR], CHECKS, MARKER, output, AUTHORITY, EVIDENCE)


def test_explicit_position_swap_remains_blocking():
    output = _output("<Subject 2> swaps positions with <Subject 1>.")
    assert not _auxiliary_wording_warnings([FLOOR], CHECKS, MARKER, output, AUTHORITY, EVIDENCE)


def test_listener_phrase_warning_requires_intact_dialogue_handoff():
    names = ["speaker_switch_listener_settle", "speaker_switch_listener_scope",
             "handoff_reasoning_schema"]
    warnings = _auxiliary_wording_warnings(names, CHECKS, MARKER, _output(), AUTHORITY, EVIDENCE)
    assert {w["original_check"] for w in warnings} == set(names)
    assert not _auxiliary_wording_warnings(
        names, {**CHECKS, "dialogue_ids_speakers_text_order": False},
        MARKER, _output(), AUTHORITY, EVIDENCE)
    assert {w["original_check"] for w in _auxiliary_wording_warnings(
        names + ["speaker_switch_camera_evidence"],
        {**CHECKS, "speaker_switch_camera_evidence": False},
        MARKER, _output(), AUTHORITY, EVIDENCE)} == {
            "speaker_switch_camera_evidence", "handoff_reasoning_schema"}


def test_redundant_duration_and_format_do_not_override_valid_execution():
    names = ["duration_output_matches_timeline", "no_final_state_machine_terms"]
    warnings = _auxiliary_wording_warnings(names, CHECKS, MARKER, _output(), AUTHORITY, EVIDENCE)
    assert {w["original_check"] for w in warnings} == set(names)
    assert not _auxiliary_wording_warnings(
        names + ["prompt_duration_matches_timeline"],
        {**CHECKS, "prompt_duration_matches_timeline": False},
        MARKER, _output(), AUTHORITY, EVIDENCE)


def test_visual_anchor_id_is_a_real_source_but_unknown_id_blocks():
    sample = json.loads((Path(__file__).parent / "fixtures" / "h3_v5_approved_c1.json").read_text())
    anchor = sample["authority"]["anchor_policy"]["catalog"][0]
    output = copy.deepcopy(sample["output"])
    requirement = output["canonical_visual_requirements"][0]
    requirement.update(source_id=anchor["anchor_id"],
                       source_excerpt=anchor["visual_reference_description"][:60])
    def audit(value):
        return check_authority(sample["raw_prompt"], value, sample["authority"],
                               sample["initial"], sample["limits"])
    assert audit(output)["passed"]
    requirement["source_id"] = "KF999"
    result = audit(output)
    assert not result["passed"]
    assert "canonical_visual_requirement_trace" in result["blocking_findings"]
