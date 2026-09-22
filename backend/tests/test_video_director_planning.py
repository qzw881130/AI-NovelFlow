import json
from types import SimpleNamespace

from app.api.shots import _build_keyframe_planner_user_content, _build_keyframe_transition_user_content


def _shot_with_timed_dialogue_source():
    return SimpleNamespace(
        id="shot-5",
        index=5,
        description="百姓看向游行队伍",
        video_description="百姓1持续低声说话",
        characters=json.dumps(["百姓1", "百姓2", "皇帝", "群臣1", "群臣2"], ensure_ascii=False),
        scene="街道",
        props="[]",
        duration=10,
        continuity_mode="NORMAL",
        dialogues=json.dumps([{
            "order": 1,
            "character_name": "百姓1",
            "text": "他确实没穿衣服……",
            "emotion_prompt": "压低声音，带着犹豫和逐渐确信的不安",
        }], ensure_ascii=False),
    )


def _payload(user_content: str) -> dict:
    return json.loads(user_content.split("\n\n", 1)[1])


def test_keyframe_planner_receives_dialogue_timeline_without_old_descriptions():
    shot = _shot_with_timed_dialogue_source()
    plan = {
        "selected_mode": "MULTI_KEYFRAME",
        "execution_windows": [{"window_index": 1, "start_time": 0, "end_time": 10}],
        "keyframes": [{
            "index": 3,
            "role": "END",
            "time_seconds": 10,
            "description": "百姓1仍在开口低声说话",
        }],
    }

    payload = _payload(_build_keyframe_planner_user_content(shot, plan, {}))

    assert payload["dialogue_timeline_source"][0] == {
        "id": "D1",
        "speaker": "百姓1",
        "text": "他确实没穿衣服……",
        "start_time": 1.0,
        "end_time": 3.99,
        "duration": 2.99,
        "min_required_duration": 2.99,
        "duration_sufficient": True,
        "emotion_prompt": "压低声音，带着犹豫和逐渐确信的不安",
    }
    assert payload["existing_keyframes"] == [{"index": 3, "role": "END", "time_seconds": 10}]
    assert "description" not in payload["existing_keyframes"][0]


def test_transition_planner_receives_full_timeline_for_each_segment():
    shot = _shot_with_timed_dialogue_source()
    first_segment = _payload(_build_keyframe_transition_user_content(
        shot,
        {"index": 1, "role": "START", "time_seconds": 0, "description": "起点"},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 5, "description": "中点"},
        1,
    ))
    second_segment = _payload(_build_keyframe_transition_user_content(
        shot,
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 5, "description": "中点"},
        {"index": 3, "role": "END", "time_seconds": 10, "description": "终点"},
        2,
    ))

    assert first_segment["dialogue_timeline_source"][0]["start_time"] == 1.0
    assert first_segment["dialogue_timeline_source"][0]["end_time"] == 3.99
    assert first_segment["segment_dialogue_state"]["overlapping_dialogue_ids"] == ["D1"]
    assert second_segment["dialogue_timeline_source"][0]["id"] == "D1"
    assert second_segment["segment_dialogue_state"]["overlapping_dialogue_ids"] == []
    assert "speech_rule" not in second_segment["segment_dialogue_state"]
