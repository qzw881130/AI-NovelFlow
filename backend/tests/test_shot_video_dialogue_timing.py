from app.services.shot_video_service import _clip_dialogues_for_prompt, _dialogue_assignment_source
from app.services.video_director_ai import build_dialogue_timeline


def test_h3_clip_dialogue_filter_prefers_official_timeline_over_position_fallback():
    dialogues = [
        {"character_name": "骗子1", "text": "第一句。", "order": 1},
        {"character_name": "骗子2", "text": "第二句。", "order": 2},
        {"character_name": "骗子1", "text": "把那根红线从下面穿过去。", "order": 3},
    ]
    official_timeline = [
        {"id": "D1", "start_time": 1.0, "end_time": 4.3},
        {"id": "D2", "start_time": 4.7, "end_time": 7.38},
        {"id": "D3", "start_time": 7.78, "end_time": 12.01},
    ]

    c1 = _clip_dialogues_for_prompt(dialogues, {"start_time": 0, "end_time": 15}, 28, official_timeline)
    c2 = _clip_dialogues_for_prompt(dialogues, {"start_time": 15, "end_time": 28}, 28, official_timeline)

    assert [item["text"] for item in c1] == [item["text"] for item in dialogues]
    assert c2 == []
    assert all(item["dialogue_timing_source"] == "official" for item in c1)
    h3_c1, _ = build_dialogue_timeline({"clip_index": 1, "start_time": 0, "end_time": 15}, c1, ["老大臣"])
    h3_c2, _ = build_dialogue_timeline({"clip_index": 2, "start_time": 15, "end_time": 28}, c2, ["老大臣"])
    assert [(item["id"], item["start_time"], item["end_time"]) for item in h3_c1] == [
        ("D1", 1.0, 4.3), ("D2", 4.7, 7.38), ("D3", 7.78, 12.01),
    ]
    assert h3_c2 == []


def test_dialogue_assignment_source_preserves_official_provenance_for_matches():
    assert _dialogue_assignment_source([{"id": "D1", "start_time": 1.0, "end_time": 4.3}]) == "official_timeline"


def test_dialogue_assignment_source_preserves_official_provenance_for_empty_clip_result():
    official_timeline = [{"id": "D1", "start_time": 1.0, "end_time": 4.3}]
    assert _clip_dialogues_for_prompt(
        [{"character_name": "骗子1", "text": "第一句。", "order": 1}],
        {"start_time": 15, "end_time": 28},
        28,
        official_timeline,
    ) == []
    assert _dialogue_assignment_source(official_timeline) == "official_timeline"


def test_dialogue_assignment_source_uses_legacy_without_official_timeline():
    assert _dialogue_assignment_source(None) == "legacy_estimated_fallback"
