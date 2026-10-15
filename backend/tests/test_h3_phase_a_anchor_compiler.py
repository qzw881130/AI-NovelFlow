"""Frozen real compiler snapshots only: no prepare, #14/#14A, DB or network."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.services import h3_single_stage_experiment as stage
from app.services.h3_native_prompt import SECTIONS, dialogue_events, sections


FIXTURES = Path(__file__).parent / "fixtures/h3_multi_keyframe_phase_a/anchor_compiler"


def saved(name="shot3_c6_extend"):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def no_external_stages(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Compiler replay must not call another stage or service")
    from app.services import h3_execution_optimizer
    from app.services.llm_service import LLMService
    from app.services.comfyui.client import ComfyUIClient
    monkeypatch.setattr(stage, "prepare_multi_keyframe_phase_a", forbidden)
    monkeypatch.setattr(h3_execution_optimizer, "check_authority", forbidden)
    monkeypatch.setattr(LLMService, "chat_completion", forbidden)
    monkeypatch.setattr(ComfyUIClient, "queue_prompt", forbidden)


def test_real_extend_only_retention_changes_and_director_stays_exact():
    case = saved()
    original = deepcopy(case)
    result = stage.compile_multi_keyframe_phase_a(case["prepared"], case["director_text"])
    assert result["status"] == "CANDIDATE_FOR_REVIEW"
    assert all(result["review"]["structure"].values())
    assert all(result["review"]["structured_authority"].values())
    before, after = sections(case["baseline_prompt"]), sections(result["prompt"])
    assert list(after) == list(SECTIONS)
    for heading in SECTIONS:
        if heading != "retention_analysis":
            assert after[heading] == before[heading]
    notes = result["review"]["compiler_owned_execution_notes"]
    assert after["retention_analysis"] == before["retention_analysis"] + "\n" + "\n".join(notes)
    assert result["director_text"] == case["director_text"]
    assert result["execution_decisions"] == case["prepared"]["llm_input"]["frozen_execution"]
    assert case == original
    assert stage.compile_multi_keyframe_phase_a(case["prepared"], case["director_text"])["prompt"] == result["prompt"]
    assert not result["submission_authorized"] and not result["production_preflight_passed"]


def test_actual_arrivals_current_pictures_and_dropped_actions():
    case = saved()
    result = stage.compile_multi_keyframe_phase_a(case["prepared"], case["director_text"])
    notes = result["review"]["compiler_owned_execution_notes"]
    assert "KF9 (<Picture 1>): reach its Canonical visual target at 1.85s in GENERATION_LOCAL_SECONDS; BEFORE D27 (starts at 1.9s)." in notes
    assert "KF12 (<Picture 2>): reach its Canonical visual target at 9.7s in GENERATION_LOCAL_SECONDS; AFTER D30 (ends at 9.65s)." in notes
    assert "KF10, KF11: no reference-image arrival constraint; their Canonical actions and state outcomes remain required." in notes
    # The old KF12 source slot was Picture 4; only the selected physical mapping is used.
    assert not any("KF12 (<Picture 4>)" in n for n in notes)
    assert not any("KF10" in n and " at " in n or "KF11" in n and " at " in n for n in notes)
    assert result["reference_manifest"] == case["prepared"]["reference_manifest"]
    assert result["picture_audit"]["passed"]
    assert "转向总管" in sections(result["prompt"])["detailed_description"]
    assert "退开半步并站稳" in sections(result["prompt"])["detailed_description"]


def test_overlap_and_spoken_events_not_mistaken_for_anchor_mentions():
    case = saved()
    result = stage.compile_multi_keyframe_phase_a(case["prepared"], case["director_text"])
    notes = result["review"]["compiler_owned_execution_notes"]
    assert any("0–1.625s in GENERATION_LOCAL_SECONDS" in n and "included in the 10.0s" in n for n in notes)
    assert result["review"]["verified_overlap_seconds"] == 1.625
    before = dialogue_events(case["baseline_prompt"])
    after = dialogue_events(result["prompt"])
    for key in ("speaker", "speaker_id", "exact_dialogue", "speech_lead"):
        assert [e[key] for e in after] == [e[key] for e in before]
    assert len(after) == 4
    assert result["review"]["structure"]["dialogue_time_cues"]
    # Raw legacy diagnostics remain visible; no production checker was relaxed.
    assert not result["review"]["native_prompt_diagnostics"]["dialogue_time_cues"]
    assert not result["review"]["native_prompt_diagnostics"]["timing_internal_only"]


def test_generate_saved_real_round2_candidate_is_byte_identical():
    case = saved("shot12_c1_generate")
    result = stage.compile_multi_keyframe_phase_a(case["prepared"], case["director_text"])
    assert result["status"] == "CANDIDATE_FOR_REVIEW"
    assert result["prompt"] == case["baseline_prompt"]
    assert result["review"]["compiler_owned_execution_notes"] == []
    assert all(result["review"]["structure"].values())
    assert all(result["review"]["structured_authority"].values())


def test_existing_assembler_without_phase_a_option_is_byte_identical():
    case = saved()
    p = case["prepared"]
    prompt, _, _ = stage.assemble_authority_owned_candidate(
        case["director_text"], p["canonical"], p["timing"], p["subject_names"],
        p["picture_mapping"], p["continuation"], p["verified_music"],
        director_only=True, character_appearances=p["character_appearances"])
    assert prompt == case["baseline_prompt"]


@pytest.mark.parametrize("value", [-1, 11, float("nan"), float("inf"), True])
def test_invalid_frozen_arrival_not_emitted_or_retimed(value):
    case = saved()
    p = case["prepared"]
    p["llm_input"]["frozen_execution"]["anchor_decisions"][0]["optimized_time"] = value
    result = stage.compile_multi_keyframe_phase_a(p, case["director_text"])
    assert result["status"] == "NOT_COVERED" and "prompt" not in result


@pytest.mark.parametrize("fault", ["time_domain", "relation", "dialogue_id", "timing"])
def test_unverified_structured_fact_never_guessed(fault):
    case = saved()
    frozen = case["prepared"]["llm_input"]["frozen_execution"]
    choice = frozen["anchor_decisions"][0]
    if fault == "time_domain": choice["optimized_time_base"] = "CLIP_STORY_SECONDS"
    elif fault == "relation": choice["arrival_relation"]["position"] = "AFTER"
    elif fault == "dialogue_id": choice["arrival_relation"]["dialogue_id"] = "D999"
    else: frozen["timing"]["optimized_duration"] = 11.625
    result = stage.compile_multi_keyframe_phase_a(case["prepared"], case["director_text"])
    assert result["status"] == "NOT_COVERED" and "prompt" not in result


def test_keep_without_picture_and_during_relation_are_serialized_without_invention():
    # Structured serializer fixture, not a new plan for the saved sample.
    frozen = {"timing": {"optimized_duration": 10, "dialogue_events": [
        {"id": "D1", "optimized_start": 2, "optimized_end": 4}]},
        "anchor_catalog": [{"anchor_id": "KF1", "linked_anchor_id": None}],
        "anchor_decisions": [{"id": "KF1", "decision": "KEEP", "original_time": 99,
            "optimized_time": 3.123456789, "optimized_time_base": "GENERATION_LOCAL_SECONDS",
            "arrival_relation": {"dialogue_id": "D1", "position": "DURING"}}]}
    notes = stage._frozen_anchor_execution_notes(frozen, frozen["timing"], [], None)
    assert notes[-1] == "KF1: reach its Canonical visual target at 3.123456789s in GENERATION_LOCAL_SECONDS; DURING D1 (2–4s)."
    assert "Picture" not in "\n".join(notes)


@pytest.mark.parametrize("fault", ["repeat", "missing", "renumber"])
def test_director_dialogue_slot_protection_remains(fault):
    case = saved()
    replacement = {"repeat": "[[SPEECH_1]][[SPEECH_1]]", "missing": "", "renumber": "[[SPEECH_99]]"}[fault]
    raw = case["director_text"].replace("[[SPEECH_1]]", replacement)
    assert stage.compile_multi_keyframe_phase_a(case["prepared"], raw)["status"] == "NOT_COVERED"


def test_no_production_dispatch_to_phase_a_compiler():
    root = Path(__file__).resolve().parents[1]
    for directory in (root / "app/api", root / "app/services"):
        for path in directory.rglob("*.py"):
            if path.name == "h3_single_stage_experiment.py":
                continue
            assert "compile_multi_keyframe_phase_a" not in path.read_text()
