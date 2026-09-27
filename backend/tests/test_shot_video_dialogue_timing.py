from app.services.shot_video_service import _clip_dialogues_for_prompt, _dialogue_assignment_source
from app.services.video_director_ai import align_clip_boundaries_to_dialogue_gaps, build_dialogue_timeline
from app.services.shot_video_service import _clip_dialogues_for_prompt


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
    h3_c1, _, c1_status = build_dialogue_timeline({"clip_index": 1, "start_time": 0, "end_time": 15}, c1, ["老大臣"])
    h3_c2, _, c2_status = build_dialogue_timeline({"clip_index": 2, "start_time": 15, "end_time": 28}, c2, ["老大臣"])
    assert [(item["id"], item["start_time"], item["end_time"]) for item in h3_c1] == [
        ("D1", 1.0, 4.3), ("D2", 4.7, 7.38), ("D3", 7.78, 12.01),
    ]
    assert h3_c2 == []
    assert c1_status["status"] == c2_status["status"] == "ok"


def test_qwen_calibrated_estimator_and_short_dialogue_gap_do_not_accumulate_padding():
    from app.services.video_director_ai import _estimate_dialogue_seconds

    assert _estimate_dialogue_seconds("怎么？") == 0.5
    assert _estimate_dialogue_seconds("怎么？", "缓慢、庄严、沉稳") == 0.5
    short_lines = [{"character_name": "甲", "text": "好。"} for _ in range(10)]
    timeline, _, status = build_dialogue_timeline(
        {"start_time": 0, "end_time": 10}, short_lines, ["甲"]
    )
    assert status["status"] == "ok"
    assert status["estimated_speech_duration"] == 5.0
    assert status["dialogue_gap_duration"] == 1.8
    assert timeline[-1]["end_time"] == 7.8


def test_shot17_qwen_estimator_timeline_fits_without_overlap():
    dialogues = [
        ("皇帝", "你们需要什么？"),
        ("高个骗子", "最上等的金丝。"),
        ("矮个骗子", "还有最柔软的丝绸。"),
        ("高个骗子", "越多越好。"),
        ("矮个骗子", "除此之外，还需要一间安静、宽敞而明亮的织造室。"),
        ("皇帝", "都给他们。"),
        ("宫廷总管", "陛下，宫中最好的金丝库存……"),
        ("皇帝", "怎么？"),
        ("宫廷总管", "没有什么，陛下。"),
        ("皇帝", "他们要多少，就给多少。"),
        ("高个骗子", "陛下的慷慨，一定会让这件衣裳成为世界上最伟大的杰作。"),
    ]
    raw = [{"character_name": speaker, "text": text} for speaker, text in dialogues]
    timeline, _, status = build_dialogue_timeline(
        {"start_time": 0, "end_time": 28}, raw, ["皇帝", "高个骗子", "矮个骗子", "宫廷总管"]
    )
    assert status == {
        "status": "ok",
        "estimated_speech_duration": 25.0,
        "dialogue_gap_duration": 2.0,
        "lead_in_duration": 1.0,
        "overflow_seconds": 0.0,
    }
    assert len(timeline) == 11
    assert timeline[0]["start_time"] == 1.0
    assert timeline[-1]["end_time"] == 28.0
    assert all(left["end_time"] <= right["start_time"] for left, right in zip(timeline, timeline[1:]))
    assert [(item["start_time"], item["end_time"]) for item in timeline] == [
        (1.0, 2.5), (2.7, 4.2), (4.4, 6.4), (6.6, 7.6), (7.8, 12.8),
        (13.0, 14.0), (14.2, 16.95), (17.15, 17.65), (17.85, 19.35),
        (19.55, 21.8), (22.0, 28.0),
    ]


def test_overflow_returns_no_official_speaking_timeline():
    dialogues = [{"character_name": "甲", "text": "很长很长很长很长很长很长很长的一句话。"}]
    timeline, silent, status = build_dialogue_timeline(
        {"start_time": 0, "end_time": 2}, dialogues, ["甲"]
    )
    assert timeline == []
    assert silent == ["甲"]
    assert status["status"] == "overflow"
    assert status["estimated_speech_duration"] > 2
    assert status["overflow_seconds"] > 0


def test_official_timeline_projects_into_clip_windows_without_repacking():
    dialogues = [
        {"character_name": "甲", "text": "第一句。"},
        {"character_name": "乙", "text": "第二句。"},
    ]
    official = [
        {"id": "D1", "speaker": "甲", "text": "第一句。", "start_time": 1.0, "end_time": 4.0},
        {"id": "D2", "speaker": "乙", "text": "第二句。", "start_time": 14.2, "end_time": 16.95},
    ]
    c1 = _clip_dialogues_for_prompt(dialogues, {"start_time": 0, "end_time": 15}, 28, official)
    c2 = _clip_dialogues_for_prompt(dialogues, {"start_time": 15, "end_time": 28}, 28, official)
    assert [(item["dialogue_id"], item["start_time"], item["end_time"], item["local_end_time"]) for item in c1] == [
        ("D1", 1.0, 4.0, 4.0), ("D2", 14.2, 15.0, 15.0)
    ]
    assert [(item["dialogue_id"], item["start_time"], item["end_time"], item["local_start_time"], item["local_end_time"]) for item in c2] == [
        ("D2", 15.0, 16.95, 0.0, 1.95)
    ]
    timeline, _, status = build_dialogue_timeline({"start_time": 0, "end_time": 15}, c1, ["甲", "乙"])
    assert [(item["id"], item["start_time"], item["end_time"], item["text"]) for item in timeline] == [
        ("D1", 1.0, 4.0, "第一句。"), ("D2", 14.2, 15.0, "第二句。")
    ]
    assert status["source"] == "official_projection"

    c2_timeline, _, _ = build_dialogue_timeline({"start_time": 15, "end_time": 28}, c2, ["甲", "乙"])
    assert [(item["id"], item["start_time"], item["end_time"], item["shot_start_time"], item["shot_end_time"]) for item in c2_timeline] == [
        ("D2", 0.0, 1.95, 15.0, 16.95)
    ]


def test_clip_boundary_moves_to_dialogue_gap():
    clips = [
        {"clip_index": 1, "start_time": 0, "end_time": 15},
        {"clip_index": 2, "start_time": 15, "end_time": 28},
    ]
    official = [
        {"id": "D6", "start_time": 13.0, "end_time": 14.0},
        {"id": "D7", "start_time": 14.2, "end_time": 16.95},
    ]
    aligned = align_clip_boundaries_to_dialogue_gaps(clips, official, 15)
    assert aligned[0]["end_time"] == 14.2
    assert aligned[1]["start_time"] == 14.2
    assert aligned[0]["end_time"] < official[1]["end_time"]


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
