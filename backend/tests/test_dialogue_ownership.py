from app.services.dialogue_ownership import assign_dialogues_to_clips


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
