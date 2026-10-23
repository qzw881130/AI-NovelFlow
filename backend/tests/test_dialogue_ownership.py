from copy import deepcopy

import pytest

from app.services.dialogue_ownership import assign_dialogues_to_clips, validate_dialogue_assignments


def test_dialogue_assignment_keeps_order_and_exact_text_across_clip_boundaries():
    dialogues = [
        {"character_name": "A", "text": "第一句很长很长很长很长很长很长很长很长很长很长。", "order": 1},
        {"character_name": "B", "text": "第二句。", "order": 2},
    ]
    clips = [
        {"clip_index": 1, "start_time": 0, "end_time": 5},
        {"clip_index": 2, "start_time": 5, "end_time": 10},
    ]

    assignments, validation = assign_dialogues_to_clips(dialogues, clips)

    spans = [item for clip in assignments for item in clip["dialogues"]]
    assert "".join(item["text"] for item in spans if item["dialogue_id"] == "D1") == dialogues[0]["text"]
    assert "".join(item["text"] for item in spans if item["dialogue_id"] == "D2") == dialogues[1]["text"]
    assert [item["source_order"] for item in spans] == sorted(item["source_order"] for item in spans)
    assert any(item["dialogue_id"] == "D1" and item["is_continuation"] for clip in assignments for item in clip["dialogues"])
    assert validation["passed"]


def test_dialogue_assignment_emits_no_duplicate_or_missing_spans():
    dialogues = [{"character_name": "A", "text": "甲乙丙丁戊己庚辛壬癸", "order": 1}]
    clips = [
        {"clip_index": 1, "start_time": 0, "end_time": 4},
        {"clip_index": 2, "start_time": 4, "end_time": 8},
        {"clip_index": 3, "start_time": 8, "end_time": 12},
    ]

    assignments, validation = assign_dialogues_to_clips(dialogues, clips)
    spans = [item for clip in assignments for item in clip["dialogues"]]

    assert "".join(item["text"] for item in spans) == dialogues[0]["text"]
    assert len({(item["dialogue_id"], item["segment_index"]) for item in spans}) == len(spans)
    assert validation == {
        "passed": True,
        "findings": [],
        "source_dialogue_count": 1,
        "assigned_segment_count": len(spans),
    }


def test_official_dialogue_timeline_controls_shot_34_clip_assignment():
    dialogues = [
        {"character_name": "骗子1", "text": "“这一段再收紧一点。”", "order": 1},
        {"character_name": "骗子2", "text": "“金色已经够了。”", "order": 2},
        {"character_name": "骗子1", "text": "“把那根红线从下面穿过去。”", "order": 3},
    ]
    official_timeline = [
        {"id": "D1", "speaker": "骗子1", "text": dialogues[0]["text"], "start_time": 1.0, "end_time": 4.3},
        {"id": "D2", "speaker": "骗子2", "text": dialogues[1]["text"], "start_time": 4.7, "end_time": 7.38},
        {"id": "D3", "speaker": "骗子1", "text": dialogues[2]["text"], "start_time": 7.78, "end_time": 12.01},
    ]
    clips = [
        {"clip_index": 1, "start_time": 0, "end_time": 15},
        {"clip_index": 2, "start_time": 15, "end_time": 28},
    ]

    assignments, validation = assign_dialogues_to_clips(dialogues, clips, official_timeline)

    assigned_by_clip = {item["clip_index"]: item["dialogues"] for item in assignments}
    all_assigned = [item for clip in assignments for item in clip["dialogues"]]
    assert [item["text"] for item in assigned_by_clip[1]] == [item["text"] for item in dialogues]
    assert assigned_by_clip[2] == []
    assert all(item["start_time"] >= 0 and item["end_time"] <= 15 for item in assigned_by_clip[1])
    assert validation["passed"]


def test_dialogue_without_official_timing_uses_legacy_fallback():
    dialogues = [
        {"character_name": "A", "text": "第一句。", "order": 1},
        {"character_name": "B", "text": "第二句。", "order": 2},
    ]
    clips = [
        {"clip_index": 1, "start_time": 0, "end_time": 5},
        {"clip_index": 2, "start_time": 5, "end_time": 10},
    ]

    assignments, validation = assign_dialogues_to_clips(dialogues, clips, [{"id": "D1"}])

    assert sum(len(item["dialogues"]) for item in assignments) > 0
    assert validation["passed"]


def _canonical_segments():
    dialogues = [
        {"dialogue_id": "event-A", "character_name": "甲", "text": "完整原文不能按时间拆成字串。", "order": 1},
        {"dialogue_id": "event-B", "character_name": "乙", "text": "第二句。", "order": 2},
    ]
    timeline = [
        {"id": "event-A", "speaker": "甲", "text": dialogues[0]["text"], "start_time": 1, "end_time": 8},
        {"id": "event-B", "speaker": "乙", "text": dialogues[1]["text"], "start_time": 8.2, "end_time": 9.5},
    ]
    clips = [{"clip_index": 1, "start_time": 0, "end_time": 5},
             {"clip_index": 2, "start_time": 5, "end_time": 10}]
    return dialogues, timeline, clips


def test_canonical_event_crosses_clips_with_exact_text_and_complete_timing_coverage():
    dialogues, timeline, clips = _canonical_segments()
    assignments, validation = assign_dialogues_to_clips(dialogues, clips, timeline)
    first, continuation = assignments[0]["dialogues"][0], assignments[1]["dialogues"][0]
    assert validation == {"passed": True, "findings": [], "source_dialogue_count": 2, "assigned_segment_count": 3}
    assert first["dialogue_id"] == continuation["dialogue_id"] == "event-A"
    assert first["text"] == continuation["text"] == dialogues[0]["text"]
    assert (first["start_time"], first["end_time"], continuation["start_time"], continuation["end_time"]) == (1, 5, 5, 8)
    assert (first["is_continuation"], first["continues_in_next_clip"]) == (False, True)
    assert (continuation["segment_index"], continuation["is_continuation"], continuation["continues_in_next_clip"]) == (2, True, False)
    # Existing H3 projection keeps exact event authority and continuation timing.
    from app.services.video_director_ai import build_dialogue_timeline, _render_dialogue_timeline_block
    projected = [{**continuation, "projection_mode": "intersection"}]
    h3_events, _, status = build_dialogue_timeline(clips[1], projected, ["甲", "乙"])
    assert status["source"] == "official_projection"
    assert h3_events[0]["text"] == dialogues[0]["text"]
    assert (h3_events[0]["start_time"], h3_events[0]["end_time"]) == (0, 3)
    block = _render_dialogue_timeline_block(h3_events, [], {"甲": "<Subject 1>"})
    assert "continuation of the same utterance; do not restart or repeat its earlier part" in block
    assert block.count(dialogues[0]["text"]) == 1


def test_official_single_clip_preserves_exact_event_authority():
    dialogues, timeline, _ = _canonical_segments()
    assignments, validation = assign_dialogues_to_clips(dialogues, [{"clip_index": 1, "start_time": 0, "end_time": 10}], timeline)
    assert validation["passed"]
    assert [s["text"] for s in assignments[0]["dialogues"]] == [d["text"] for d in dialogues]
    assert all(not s["is_continuation"] and not s["continues_in_next_clip"] for s in assignments[0]["dialogues"])


@pytest.mark.parametrize("case,code", [
    ("missing", "DIALOGUE_EVENT_ID_MISSING_OR_ADDED"),
    ("unknown", "DIALOGUE_EVENT_ID_MISSING_OR_ADDED"),
    ("speaker", "DIALOGUE_SPEAKER_CHANGED"),
    ("text", "DIALOGUE_TEXT_MISSING_OR_CHANGED"),
    ("gap", "DIALOGUE_SEGMENT_TIMING_GAP"),
    ("overlap", "DIALOGUE_SEGMENT_TIMING_OVERLAP"),
    ("continuation", "DIALOGUE_CONTINUATION_INVALID"),
    ("next_continuation", "DIALOGUE_CONTINUATION_INVALID"),
    ("segment_index", "DIALOGUE_CONTINUATION_INVALID"),
    ("order", "DIALOGUE_ORDER_CHANGED"),
    ("out_of_event", "DIALOGUE_SEGMENT_TIMING_INVALID"),
    ("nonfinite", "DIALOGUE_SEGMENT_TIMING_INVALID"),
])
def test_canonical_segment_corruption_is_blocking(case, code):
    dialogues, timeline, clips = _canonical_segments()
    assignments, _ = assign_dialogues_to_clips(dialogues, clips, timeline)
    first, continuation = assignments[0]["dialogues"][0], assignments[1]["dialogues"][0]
    if case == "missing": assignments[1]["dialogues"].pop()
    elif case == "unknown": continuation["dialogue_id"] = "invented-event"
    elif case == "speaker": continuation["speaker"] = "错误人物"
    elif case == "text": continuation["text"] += "改写"
    elif case == "gap": continuation["start_time"] = 5.1
    elif case == "overlap":
        clips[0]["end_time"] = first["end_time"] = 5.1
    elif case == "continuation": continuation["is_continuation"] = False
    elif case == "next_continuation": first["continues_in_next_clip"] = False
    elif case == "segment_index": continuation["segment_index"] = 1
    elif case == "order": assignments[1]["dialogues"].reverse()
    elif case == "out_of_event": continuation["end_time"] = 8.1
    elif case == "nonfinite": continuation["end_time"] = float("nan")
    validation = validate_dialogue_assignments(dialogues, assignments, timeline, clips)
    assert validation["passed"] is False
    assert code in validation["findings"]


@pytest.mark.parametrize("field,value,code", [
    ("id", "invented-event", "DIALOGUE_EVENT_ID_MISSING_OR_ADDED"),
    ("speaker", "错误人物", "DIALOGUE_SPEAKER_CHANGED"),
    ("text", "错误原文", "DIALOGUE_TEXT_MISSING_OR_CHANGED"),
])
def test_official_event_identity_speaker_and_text_cannot_drift(field, value, code):
    dialogues, timeline, clips = _canonical_segments()
    timeline[0][field] = value
    assignments, validation = assign_dialogues_to_clips(dialogues, clips, timeline)
    assert validation["passed"] is False
    assert code in validation["findings"]
    if field == "id":
        assert all(s["dialogue_id"] != "event-A" for a in assignments for s in a["dialogues"])


def test_real_d6_boundary_replays_as_one_event_with_two_segments():
    text = "王城里能织锦缎的工匠多得很，凭什么要让陛下见你们？"
    dialogues = [{"dialogue_id": "D6", "character_name": "卫兵1", "text": text}]
    timeline = [{"id": "D6", "speaker": "卫兵1", "text": text, "start_time": 19.5, "end_time": 25.25}]
    clips = [{"clip_index": 2, "start_time": 7.95, "end_time": 21},
             {"clip_index": 3, "start_time": 21, "end_time": 35.1}]
    before = deepcopy(dialogues)
    assignments, validation = assign_dialogues_to_clips(dialogues, clips, timeline)
    assert validation["passed"]
    assert validation["source_dialogue_count"] == 1 and validation["assigned_segment_count"] == 2
    assert [a["dialogues"][0]["text"] for a in assignments] == [text, text]
    assert dialogues == before
