"""Offline #10A input and contract checks using saved Shot 12 timing facts."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import clip_planner as planner
from app.services.clip_duration_planning import observe_duration_plan
from app.services.clip_planner import (
    _build_temporal_anchors,
    _project_clip_visual_states,
    _project_dialogue_speaker_groups,
    _project_early_composition_states,
    _project_temporal_targets,
    build_clip_planner_input,
)
from app.services.clip_validator import validate_clip_plan
from app.services.dialogue_ownership import assign_dialogues_to_clips
from app.services.shot_video_service import _project_semantic_clip_transitions


SHOT12_C2_C3 = [
    ("D7", "皇帝", 15.45, 17.45), ("D8", "皇帝", 17.65, 19.15),
    ("D9", "宫廷总管", 19.35, 20.85), ("D10", "皇帝", 21.05, 23.05),
    ("D11", "皇帝", 23.25, 26.75), ("D12", "宫廷总管", 26.95, 28.20),
    ("D13", "皇帝", 28.40, 28.90), ("D14", "皇帝", 29.10, 32.85),
    ("D15", "皇帝", 33.05, 35.80), ("D16", "皇帝", 36.00, 41.25),
    ("D17", "皇帝", 41.45, 42.70),
]
SPEAKER_IDS = {"皇帝": "bbfa698b-e38e-40db-8cc9-ae0ab381fc4f",
               "宫廷总管": "2eab8846-dc86-4e12-8c30-dfeca26cc6c5"}


def timeline(rows):
    return [dict(id=event_id, speaker=speaker, text=f"{event_id} 原文", start_time=start, end_time=end)
            for event_id, speaker, start, end in rows]


def test_saved_shot12_speaker_runs_are_compact_and_not_new_dialogue_authority():
    source = timeline(SHOT12_C2_C3)
    original = copy.deepcopy(source)
    context = {"events": [
        {"dialogue_id": event["id"],
         "resolved_character": {"status": "resolved", "character_id": SPEAKER_IDS[event["speaker"]]}}
        for event in source
    ]}
    groups = _project_dialogue_speaker_groups(source, context)
    assert [g["dialogue_ids"] for g in groups] == [
        ["D7", "D8"], ["D9"], ["D10", "D11"], ["D12"], ["D13", "D14", "D15", "D16", "D17"]]
    assert [(g["speaker_id"], g["start_time"], g["end_time"], g["dialogue_count"]) for g in groups[:4]] == [
        (SPEAKER_IDS["皇帝"], 15.45, 19.15, 2),
        (SPEAKER_IDS["宫廷总管"], 19.35, 20.85, 1),
        (SPEAKER_IDS["皇帝"], 21.05, 26.75, 2),
        (SPEAKER_IDS["宫廷总管"], 26.95, 28.20, 1),
    ]
    assert source == original
    assert all("text" not in group for group in groups)
    context["events"][0]["resolved_character"] = {"status": "unresolved", "character_id": None}
    assert _project_dialogue_speaker_groups(source, context)[0]["speaker_id"] is None
    context["events"][0]["resolved_character"] = {"status": "resolved", "character_id": "different-person"}
    assert _project_dialogue_speaker_groups(source, context)[0]["dialogue_ids"] == ["D7"]


def test_planner_input_exposes_groups_without_copying_dialogue_text():
    source = timeline(SHOT12_C2_C3)
    shot = SimpleNamespace(id="shot12-offline", duration=59, continuity_mode="CONTINUOUS_TAKE",
                           characters="[]", props="[]", dialogues=json.dumps(source, ensure_ascii=False),
                           keyframes="[]", image_url=None, image_path=None,
                           video_director_plan=json.dumps({"dialogue_timeline_source": source}, ensure_ascii=False))
    before = copy.deepcopy(vars(shot))
    payload = build_clip_planner_input(shot, [], resolved_dialogue_timeline=source)
    assert [g["dialogue_ids"] for g in payload["dialogue_speaker_groups"]] == [
        ["D7", "D8"], ["D9"], ["D10", "D11"], ["D12"], ["D13", "D14", "D15", "D16", "D17"]]
    assert all(set(g) == {"dialogue_ids", "speaker_id", "speaker", "start_time", "end_time", "dialogue_count"}
               for g in payload["dialogue_speaker_groups"])
    assert all("text" not in g for g in payload["dialogue_speaker_groups"])
    assert vars(shot) == before


def shot12_projection(boundary):
    states = [dict(visual_state_id=f"KF{index}", keyframe_index=index, time_seconds=time,
                   role="START" if index == 1 else "END" if index == 8 else "INTERMEDIATE",
                   description=f"State {index}", timed_visual_target=index == 7)
              for index, time in [(1, 0), (5, 14), (6, 17.7), (7, 42.8), (8, 59)]]
    transitions = [dict(from_keyframe_index=before, to_keyframe_index=after,
                        start_time=start, end_time=end, transition_description=f"T{before}")
                   for before, after, start, end in [(5, 6, 14, 17.7), (6, 7, 17.7, 42.8), (7, 8, 42.8, 59)]]
    windows = [(0, 15.25), (15.25, boundary), (boundary, 42.9), (42.9, 59)]
    clips = []
    for index, (start, end) in enumerate(windows, 1):
        inherited = None if index == 1 else {
            "state_id": f"KF{index + 3}", "transition_to_state_id": f"KF{index + 4}",
            "premise_preserved": True,
        }
        clips.append(dict(clip_index=index, start_time=start, end_time=end,
                          planned_duration=round(end - start, 2),
                          continuity_to_previous="NONE" if index == 1 else "CONTINUOUS",
                          previous_clip_index=None if index == 1 else index - 1,
                          selected_temporal_target_ids=["KF7"] if index == 3 else [],
                          early_composition_state_id=None, inherited_start_composition=inherited,
                          reason="Preserve adjacent canonical transition and opening composition."))
    _project_clip_visual_states(clips, states)
    _project_temporal_targets(clips, states, 59)
    source = timeline(SHOT12_C2_C3)
    speech = [dict(event_id=e["id"], start_time=e["start_time"], end_time=e["end_time"]) for e in source]
    _project_early_composition_states(clips, states, speech, transitions)
    anchors = _build_temporal_anchors(clips, states)
    structural = validate_clip_plan(59, clips, anchors, available_inputs=None, visual_state_candidates=states)
    assigned, dialogue = assign_dialogues_to_clips(source, clips, source)
    return clips, transitions, anchors, structural, assigned, dialogue, speech


def test_shot12_pairwise_boundary_candidate_preserves_existing_contracts():
    original = shot12_projection(28.9)
    candidate = shot12_projection(26.85)
    for clips, _, anchors, structural, assigned, dialogue, _ in (original, candidate):
        assert structural["passed"] and dialogue["passed"]
        assert len(clips) == 4 and len(anchors) == 1
        assert [clip["visual_state_indexes"] for clip in clips[1:3]] == [[6], [7]]
        assert clips[2]["temporal_anchor_ids"] == ["clip-3-KF7"]
        assert [d["dialogue_id"] for part in assigned for d in part["dialogues"]] == [e[0] for e in SHOT12_C2_C3]
    assert [len(part["dialogues"]) for part in original[4][1:3]] == [7, 4]
    assert [len(part["dialogues"]) for part in candidate[4][1:3]] == [5, 6]
    assert [(c["start_time"], c["end_time"]) for c in candidate[0][1:3]] == [(15.25, 26.85), (26.85, 42.9)]
    projected = [_project_semantic_clip_transitions(candidate[1], clip["visual_state_indexes"],
                 clip["carry_in_state_index"], clip_start=clip["start_time"], clip_end=clip["end_time"])
                 for clip in candidate[0][1:3]]
    assert [[round(t["clip_local_end_time"] - t["clip_local_start_time"], 2) for t in part]
            for part in projected] == [[2.45, 9.15], [15.95, 0.1]]


def test_shot12_budget_does_not_assume_temporal_overlap_or_fixed_switch_cost():
    original = shot12_projection(28.9)
    candidate = shot12_projection(26.85)
    budgets = {"EXTEND": {"max_duration": 20, "overlap_duration": 1.625},
               "TEMPORAL_EXTEND": {"max_duration": 20, "overlap_duration": None}}
    current_c2 = observe_duration_plan(original[0][1], original[6], budgets)
    moved_c2 = observe_duration_plan(candidate[0][1], candidate[6], budgets)
    moved_c3 = observe_duration_plan(candidate[0][2], candidate[6], budgets)
    assert (current_c2["planned_story_duration"], current_c2["fixed_dialogue_duration"],
            current_c2["minimum_execution_duration"]) == (13.65, 12.25, 13.875)
    assert (moved_c2["planned_story_duration"], moved_c2["fixed_dialogue_duration"],
            moved_c2["minimum_execution_duration"]) == (11.6, 10.5, 12.125)
    assert (moved_c3["planned_story_duration"], moved_c3["fixed_dialogue_duration"],
            moved_c3["overlap_duration"], moved_c3["minimum_execution_duration"]) == (16.05, 14.75, None, None)
    assert moved_c3["status"] == "ABOVE_PREFERRED"  # Soft, not a new gate.


def test_independent_dialogue_state_anchor_duration_and_continuity_guards_remain_blocking():
    clips, _, anchors, _, _, _, _ = shot12_projection(26.85)
    official = timeline(SHOT12_C2_C3)
    wrong_speaker = copy.deepcopy(official)
    wrong_speaker[3]["speaker"] = "宫廷总管"
    _, dialogue = assign_dialogues_to_clips(wrong_speaker, clips, official)
    assert "DIALOGUE_SPEAKER_CHANGED" in dialogue["findings"]
    wrong_text = copy.deepcopy(official)
    wrong_text[3]["text"] = "改写台词"
    _, dialogue = assign_dialogues_to_clips(wrong_text, clips, official)
    assert "DIALOGUE_TEXT_MISSING_OR_CHANGED" in dialogue["findings"]
    states = [dict(keyframe_index=index, time_seconds=time, role="START" if index == 1 else "INTERMEDIATE")
              for index, time in [(1, 0), (5, 14), (6, 17.7), (7, 42.8), (8, 59)]]
    bad_state = copy.deepcopy(clips)
    bad_state[2]["visual_state_indexes"] = [6]
    result = validate_clip_plan(59, bad_state, anchors, available_inputs=None, visual_state_candidates=states)
    assert "VISUAL_STATE_OWNERSHIP_INVALID" in [item["code"] for item in result["blocking"]]
    bad_anchor = copy.deepcopy(anchors)
    bad_anchor[0]["time_seconds"] = 99
    result = validate_clip_plan(59, clips, bad_anchor, available_inputs=None, visual_state_candidates=states)
    assert "ANCHOR_OUTSIDE_CLIP" in [item["code"] for item in result["blocking"]]
    bad_duration = copy.deepcopy(clips)
    bad_duration[2]["planned_duration"] = 21
    result = validate_clip_plan(59, bad_duration, anchors, available_inputs=None, visual_state_candidates=states)
    assert "PROVIDER_DURATION_LIMIT" in [item["code"] for item in result["blocking"]]
    bad_continuity = copy.deepcopy(clips)
    bad_continuity[2]["continuity_to_previous"] = "CUT"
    result = validate_clip_plan(59, bad_continuity, anchors, available_inputs=None, visual_state_candidates=states)
    assert "TEMPORAL_EXTEND_CONTINUITY_REQUIRED" in [item["code"] for item in result["blocking"]]


def test_other_saved_shots_supply_groups_without_rule_based_split():
    controls = [
        (3, [("D7", "骗子1", 13.2, 16.2), ("D8", "骗子1", 16.4, 20.15),
             ("D9", "骗子1", 20.35, 22.35), ("D10", "骗子1", 22.55, 25.8)], 1),
        (4, [("D7", "骗子1", 13.7, 16.2), ("D8", "骗子2", 16.4, 19.9),
             ("D9", "骗子1", 20.1, 23.35), ("D10", "骗子1", 23.55, 24.05),
             ("D11", "骗子1", 24.25, 25.75), ("D12", "骗子2", 25.95, 26.45),
             ("D13", "骗子1", 26.65, 27.4)], 5),
        (9, [("D1", "皇帝", 1, 2.5), ("D2", "宫廷总管", 2.7, 4.95)], 2),
    ]
    for _, rows, expected_groups in controls:
        groups = _project_dialogue_speaker_groups(timeline(rows), {"events": []})
        assert len(groups) == expected_groups
        assert sum(g["dialogue_count"] for g in groups) == len(rows)
        assert all(g["speaker_id"] is None for g in groups)  # Unknown identity stays unknown.


@pytest.mark.asyncio
@pytest.mark.parametrize("shot_number,duration,rows,group_count", [
    (3, 12.8, [("D7", "骗子1", .1, 3.1), ("D8", "骗子1", 3.3, 7.05),
               ("D9", "骗子1", 7.25, 9.25), ("D10", "骗子1", 9.45, 12.7)], 1),
    (4, 13.9, [("D7", "骗子1", .1, 2.6), ("D8", "骗子2", 2.8, 6.3),
               ("D9", "骗子1", 6.5, 9.75), ("D10", "骗子1", 9.95, 10.45),
               ("D11", "骗子1", 10.65, 12.15), ("D12", "骗子2", 12.35, 12.85),
               ("D13", "骗子1", 13.05, 13.8)], 5),
    (9, 7, [("D1", "皇帝", 1, 2.5), ("D2", "宫廷总管", 2.7, 4.95)], 2),
])
async def test_saved_shot_controls_do_not_gain_deterministic_clips(
    monkeypatch, shot_number, duration, rows, group_count,
):
    source = timeline(rows)
    shot = SimpleNamespace(id=f"shot{shot_number}-offline", chapter_id="offline", duration=duration,
                           continuity_mode="NORMAL", characters="[]", props="[]",
                           dialogues=json.dumps(source, ensure_ascii=False), keyframes="[]",
                           image_url=None, image_path=None,
                           video_director_plan=json.dumps({"dialogue_timeline_source": source}, ensure_ascii=False))
    sent = []

    class FakeLLM:
        async def chat_completion(self, **kwargs):
            sent.append(json.loads(kwargs["user_content"]))
            return {"success": True, "content": json.dumps({"clips": [{
                "clip_index": 1, "start_time": 0, "end_time": duration,
                "continuity_to_previous": "NONE", "previous_clip_index": None,
                "selected_temporal_target_ids": [], "early_composition_state_id": None,
                "inherited_start_composition": None, "reason": "Complete visual beat.",
            }]})}

    monkeypatch.setattr(planner, "LLMService", FakeLLM)
    monkeypatch.setattr(planner, "resolve_novel_prompt_template", lambda *args: SimpleNamespace(
        template="offline #10A", name="offline #10A"))
    monkeypatch.setattr(planner, "load_planning_budgets", lambda db: {})
    clips, validation = await planner.plan_clips(None, SimpleNamespace(id="offline"), shot, [],
                                                resolved_dialogue_timeline=source)
    assert validation["passed"] and len(clips) == len(sent) == 1
    assert len(clips[0]["dialogue_assignment"]) == len(rows)
    assert len(sent[0]["dialogue_speaker_groups"]) == group_count


def test_prompt_compares_adjacent_options_without_new_output_or_hard_switch_gate():
    prompt = (Path(__file__).parents[1] / "prompt_templates/10A_NovelFlow_ClipExecutionPlanner_V1.txt").read_text()
    assert "dialogue_speaker_groups" in prompt
    assert "Compare keeping a natural Clip, moving an adjacent boundary" in prompt
    assert "Inspect both adjacent Clips" in prompt
    assert "Unknown overlap or speaker/action acquisition cost" in prompt
    assert "a speaker change does not" in prompt
    assert "A long speaker run is not indivisible" in prompt
    assert "Return JSON only:" in prompt and '"clips": [' in prompt
    assert "must not change Clip count/start/end/duration" not in prompt
    assert "Dialogue timing may influence WHERE a boundary is convenient, but nothing else" not in prompt
