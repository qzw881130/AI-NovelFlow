"""Offline request ownership and mock-response assembly; no model-quality claim."""
import copy

import pytest

from app.services import video_director_ai as h3
from test_canonical_h3_manifest_speech_authority import dialogue, invoke, state


def test_identity_source_once_and_no_invented_current_appearance(monkeypatch):
    appearances = {"Mira": "Amber eyes. Default outfit: red dress. Portrait pose: standing."}
    current = [{**state(4, 10), "description": "Mira wears a blue jacket and sits beside Jun."}]
    _, payload, call, _ = invoke(monkeypatch, states=current, appearances=appearances)
    assert call["user_content"].count(appearances["Mira"]) == 1
    assert call["user_content"].count(current[0]["description"]) == 1
    assert payload["shot"]["official_character_appearances"] == appearances
    assert payload["visual_controls"][0]["description"] == current[0]["description"]
    assert "current_appearance" not in payload["shot"]
    policy = call["system_prompt"].split("CANONICAL H3 SECTION OWNERSHIP", 1)[1]
    assert "do not treat them as current costume" in policy
    assert "No independent current Shot appearance binding is supplied" in policy


def test_transition_source_has_one_body_and_preserves_upstream_contract(monkeypatch):
    transitions = [{"from_keyframe_index": 3, "to_keyframe_index": 4,
                    "start_time": 8, "end_time": 14, "duration": 6,
                    "transition_description": "Mira lifts the box and turns toward KF4."}]
    before = copy.deepcopy(transitions)
    _, payload, call, _ = invoke(monkeypatch, transitions=transitions)
    assert payload["transitions"] == transitions == before
    assert call["user_content"].count(transitions[0]["transition_description"]) == 1
    assert "motion_directive" not in payload
    assert "do not fully redescribe their endpoint" in call["system_prompt"]
    assert "intersection with this Clip" in call["system_prompt"]


def test_empty_owned_extend_does_not_project_previous_state_dump(monkeypatch):
    _, payload, call, _ = invoke(monkeypatch, states=[], transitions=[])
    assert payload["visual_controls"] == []
    assert payload["clip"]["carry_in_state_index"] == 3
    assert payload["conditioning"]["previous_av_present"] is True
    assert "previous_av" in payload["conditioning"]
    assert not {"frames", "ordered_keyframes", "keyframes", "continuity_requirements"}.intersection(payload)
    assert "without describing the whole previous scene" in call["system_prompt"]
    assert "do not invent a multi-interval action script" in call["system_prompt"]


@pytest.mark.parametrize("image_backed", [False, True])
def test_linked_temporal_target_is_not_a_second_state_description(monkeypatch, image_backed):
    states = [state(4, 10), {**state(7, 16), "description": "Mira reaches the window with the box."}]
    anchors = [{"anchor_id": "selected-KF7", "time_seconds": 6,
                "source": {"keyframe_index": 7}, "description": "obsolete duplicated target"}]
    before = copy.deepcopy((states, anchors))
    _, payload, call, _ = invoke(monkeypatch, states=states, anchors=anchors,
                                capability="TEMPORAL_EXTEND", images=(7,) if image_backed else ())
    assert (states, anchors) == before
    assert payload["temporal_anchors"] == [{"anchor_id": "selected-KF7", "time_seconds": 6,
                                           "source_keyframe_index": 7, "target_state_label": "KF7"}]
    assert payload["visual_controls"][1]["time_seconds"] == 6
    assert call["user_content"].count(states[1]["description"]) == 1
    assert "obsolete duplicated target" not in call["user_content"]
    assert payload["control_counts"]["temporal_anchor_count"] == 1
    assert payload["control_counts"]["ordinary_reference_count"] == int(image_backed)


def test_unlinked_temporal_target_keeps_its_only_description(monkeypatch):
    anchors = [{"anchor_id": "external", "time_seconds": 4,
                "source": {"keyframe_index": 9}, "description": "Jun arrives at the door."}]
    _, payload, call, _ = invoke(monkeypatch, anchors=anchors, capability="TEMPORAL_EXTEND")
    assert payload["temporal_anchors"] == [{"anchor_id": "external", "time_seconds": 4,
                                           "source_keyframe_index": 9, "description": anchors[0]["description"]}]
    assert call["user_content"].count(anchors[0]["description"]) == 1


def test_generate_keeps_start_grounding_and_manifest_authority(monkeypatch):
    states = [{**state(4, 10, "START"), "description": ""}, state(7, 16)]
    _, payload, call, record = invoke(monkeypatch, states=states, images=(4,), capability="GENERATE")
    assert payload["conditioning"]["previous_av_present"] is False
    assert payload["visual_controls"][0]["description"] == ""
    assert payload["visual_controls"][0]["physical_picture"] == "<Picture 1>"
    assert payload["visual_controls"][1]["physical_picture"] is None
    assert payload["physical_picture_manifest"][0]["source_keyframe_index"] == 4
    assert record["parsed_result"]["physical_picture"]["passed"]
    assert "including non-state references" in call["system_prompt"]
    assert "Empty description is not permission to invent a pose" in call["system_prompt"]


@pytest.mark.parametrize("capability", ["GENERATE", "EXTEND", "TEMPORAL_EXTEND"])
def test_owned_format_mock_preserves_exact_speech_and_nonhuman_sound(monkeypatch, capability):
    # Authored response fixture: tests assembly, not whether a real LLM obeys policy.
    body = ("subject_definitions:\n<Subject 1> is Mira, amber-eyed.\n<Subject 2> is Jun.\n"
            "official_character_identity_lock:\nKeep identities stable; no new subjects.\n"
            "keyframe_timeline:\nKF4 at 0s: Mira wears a blue jacket.\n"
            "summary:\nUse the supplied current-state grounding.\n"
            "detailed_description:\nMira raises the box toward KF4.\n"
            "overall_soundscape:\nRoom tone, fabric rustle and wooden-box Foley.")
    events = [dialogue("Jun", "第一句。", "D1", 10.5, 12), dialogue("Mira", "第二句。", "D2", 13, 15)]
    prompt, payload, _, record = invoke(monkeypatch, body=body, dialogues=events, capability=capability)
    bindings = h3._subject_bindings(body, payload["clip_visible_characters"])
    canonical = h3._render_dialogue_timeline_block(payload["dialogue_timeline_source"], payload["silent_characters"], bindings)
    assert canonical in prompt
    assert prompt.count("amber-eyed") == prompt.count("blue jacket") == 1
    assert prompt.count("第一句。") == prompt.count("第二句。") == 1
    assert "speaker: <Subject 2>\n  start_time: 0.5s\n  end_time: 2.0s" in prompt
    assert "speaker: <Subject 1>\n  start_time: 3.0s\n  end_time: 5.0s" in prompt
    assert "Room tone, fabric rustle and wooden-box Foley." in prompt
    assert record["parsed_result"]["dialogue"]["passed"]
    assert record["parsed_result"]["physical_picture"]["passed"]


def test_old_response_is_not_silently_deduplicated(monkeypatch):
    body = "summary:\nSame visual fact.\ndetailed_description:\nSame visual fact.\noverall_soundscape:\nRoom tone."
    prompt, _, _, record = invoke(monkeypatch, body=body)
    assert prompt.count("Same visual fact.") == 2
    assert record["response"] == body
    # The implementation changes the request, not historical responses.
    assert "CANONICAL H3 SECTION OWNERSHIP" in h3._canonical_section_ownership_contract()
