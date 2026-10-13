"""Dialogue record authority uses events, not substrings in other text."""

import pytest

from app.services import video_director_ai as h3
from app.services.h3_native_prompt import check_native_prompt
from test_canonical_h3_manifest_speech_authority import dialogue, invoke, state


EVENTS = [
    {"id": "D3", "speaker": "宫女1", "text": "没有。", "start_time": 5.65,
     "end_time": 6.15, "duration_sufficient": True},
    {"id": "D4", "speaker": "侍从1", "text": "我也没有。", "start_time": 6.35,
     "end_time": 7.35, "duration_sufficient": True},
]
BINDINGS = {"宫女1": "<Subject 1>", "侍从1": "<Subject 2>"}
BODY = "summary:\n两人望向房门。\n\ndetailed_description:\n目光和姿态自然变化。"


def assembled(events=EVENTS, body=BODY):
    timeline = h3._render_dialogue_timeline_block(events, [], BINDINGS)
    return f"subject_definitions:\n<Subject 1> is 宫女1.\n<Subject 2> is 侍从1.\n\n{timeline}\n\n{body}"


def audit(prompt, events=EVENTS, body=BODY):
    return h3._audit_final_h3_prompt(
        prompt, events, [], BINDINGS, canonical_visual_body=body,
    )


def test_contained_dialogue_and_ordinary_visual_phrase_pass():
    assert audit(assembled())["passed"]
    prose = "summary:\n画面中没有。两人继续望向房门。\n\ndetailed_description:\n目光自然变化。"
    assert audit(assembled(body=prose), body=prose)["passed"]


def test_intentionally_repeated_canonical_text_uses_distinct_event_ids():
    events = [{**item, "text": "没有。"} for item in EVENTS]
    assert audit(assembled(events), events)["passed"]


def test_duplicate_complete_record_fails():
    prompt = assembled()
    d3 = prompt[prompt.index("D3:\n"):prompt.index("D4:\n")]
    prompt = prompt.replace("D4:\n", d3 + "D4:\n", 1)
    result = audit(prompt)
    assert not result["passed"]
    assert "DIALOGUE_DUPLICATED_IN_PROMPT" in result["blocking_issues"]


def test_missing_or_modified_dialogue_fails():
    prompt = assembled()
    missing = prompt.replace("  exact_dialogue: 没有。\n", "", 1)
    changed = prompt.replace("  exact_dialogue: 没有。\n", "  exact_dialogue: 有。\n", 1)
    for candidate in (missing, changed):
        result = audit(candidate)
        assert not result["passed"]
        assert "DIALOGUE_EXACT_TEXT_OCCURRENCE_INVALID" in result["blocking_issues"]


def test_swapped_speaker_or_order_fails():
    prompt = assembled()
    swapped_speakers = prompt.replace("D3:\n  speaker: <Subject 1>", "D3:\n  speaker: <Subject 2>")
    swapped_order = prompt.replace("D3:", "TEMP:", 1).replace("D4:", "D3:", 1).replace("TEMP:", "D4:", 1)
    assert "DIALOGUE_SPEAKER_TIMING_AUTHORITY_INVALID" in audit(swapped_speakers)["blocking_issues"]
    assert "DIALOGUE_ORDER_INVALID" in audit(swapped_order)["blocking_issues"]


def test_added_structured_or_explicit_outside_dialogue_fails():
    prompt = assembled()
    added = "D5:\n  speaker: <Subject 1>\n  start_time: 7.5s\n  end_time: 8.0s\n  exact_dialogue: 新台词。\n"
    assert not audit(prompt.replace("summary:\n", added + "summary:\n", 1))["passed"]
    body = BODY + "\n侍从1说道：“新台词。”"
    result = audit(assembled(body=body), body=body)
    assert "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE" in result["blocking_issues"]


@pytest.mark.parametrize("states,step", [
    ([state(4, 10)], "11"),
    ([state(4, 10, "START"), state(5, 18, "END")], "12"),
    ([state(4, 10), state(5, 14), state(6, 18, "END")], "13"),
])
def test_each_upstream_h3_route_accepts_contained_dialogue(monkeypatch, states, step):
    lines = [dialogue("Mira", "没有。", "D3", 11.0, 12.0),
             dialogue("Jun", "我也没有。", "D4", 13.0, 14.5)]
    _, _, _, call = invoke(monkeypatch, states=states, dialogues=lines)
    assert call["step"] == step
    assert call["parsed_result"]["dialogue"]["passed"]


def native_prompt(first="没有。", second="我也没有。"):
    return ("subject_definitions:\n<Subject 1> is 宫女1. <Subject 2> is 侍从1.\n"
            "summary:\nTwo people remain in view.\n"
            "retention_analysis:\nPreserve their established blocking.\n"
            "detailed_description:\n"
            f"<Subject 1> (S1) speaks, <d>[Chinese] {first}</d>\n"
            f"<Subject 2> (S2) replies, <d>[Chinese] {second}</d>\n"
            "overall_soundscape:\nRoom tone.\n"
            "non_diegetic_music:\nNone.")


def native_checks(prompt):
    canonical = [{"id": item["id"], "speaker": BINDINGS[item["speaker"]],
                  "exact_dialogue": item["text"]} for item in EVENTS]
    return check_native_prompt(prompt, canonical,
                               {"subject_bindings": {v: k for k, v in BINDINGS.items()},
                                "reference_bindings": []}, "", {"handoffs": []})[0]


def test_14_native_event_count_accepts_containment_and_rejects_duplicates():
    checks = native_checks(native_prompt())
    assert checks["native_dialogue_markup"]
    assert checks["dialogue_ids_speakers_text_order"]
    assert checks["exact_dialogue_occurrence_count"]
    duplicate = native_checks(native_prompt().replace("overall_soundscape:",
        "<Subject 1> (S1) speaks again, <d>[Chinese] 没有。</d>\noverall_soundscape:"))
    assert not duplicate["native_dialogue_markup"]
    assert not duplicate["exact_dialogue_occurrence_count"]
    changed = native_checks(native_prompt(second="我没听见。"))
    assert not changed["dialogue_ids_speakers_text_order"]
    assert not changed["exact_dialogue_occurrence_count"]


def test_14_native_plain_visual_phrase_is_not_extra_utterance():
    prompt = native_prompt().replace("Two people remain in view.", "The room has no sound; 没有。 Two people remain in view.")
    checks = native_checks(prompt)
    assert checks["exact_dialogue_occurrence_count"]
    assert checks["dialogue_ids_speakers_text_order"]
