import json
from types import SimpleNamespace

from app.api.shots import _build_keyframe_planner_user_content, _build_keyframe_transition_user_content
from app.services.shot_keyframe_service import ShotKeyframeService, sync_planned_keyframe_states


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
        "end_time": 2.75,
        "duration": 1.75,
        "estimated_speech_duration": 1.75,
        "min_required_duration": 1.75,
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
    assert first_segment["dialogue_timeline_source"][0]["end_time"] == 2.75
    assert first_segment["segment_dialogue_state"]["overlapping_dialogue_ids"] == ["D1"]
    assert second_segment["dialogue_timeline_source"][0]["id"] == "D1"
    assert second_segment["segment_dialogue_state"]["overlapping_dialogue_ids"] == []
    assert "speech_rule" not in second_segment["segment_dialogue_state"]


def test_aligned_p3_is_the_state_consumed_by_keyframe_image_without_losing_media():
    description = "Scene: palace\nCharacters:\n- 皇帝: upright\n- 骗子: attentive\nAction: all four hold position"
    shot = SimpleNamespace(video_director_plan=json.dumps({"keyframes": [
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 7.0, "description": "P2 visual state"},
        {"index": 3, "role": "INTERMEDIATE", "time_seconds": 14.2, "description": description},
    ]}, ensure_ascii=False))
    keyframes = [
        {"frame_index": 0, "plan_keyframe_index": 2, "time_seconds": 7.0,
         "description": "P2 visual state", "image_url": "p2.png"},
        {"frame_index": 1, "plan_keyframe_index": 3, "time_seconds": 15.0,
         "description": description, "image_url": "p3.png", "image_task_id": "old-task",
         "reference_mode": "auto_select", "prompt_text": "previous prompt"},
    ]

    assert sync_planned_keyframe_states(shot, keyframes)
    assert keyframes[1] == {
        "frame_index": 1, "plan_keyframe_index": 3, "time_seconds": 14.2,
        "description": description, "image_url": "p3.png", "image_task_id": "old-task",
        "reference_mode": "auto_select", "prompt_text": "previous prompt",
    }
    assert keyframes[0]["image_url"] == "p2.png"
    assert not sync_planned_keyframe_states(shot, keyframes)


def test_keyframe_image_sync_preserves_timed_visual_target():
    shot = SimpleNamespace(video_director_plan=json.dumps({"keyframes": [
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 5, "timed_visual_target": True},
    ]}))
    keyframe = {"plan_keyframe_index": 2}

    ShotKeyframeService()._sync_video_director_keyframe_image(shot, keyframe, "/kf2.png", "task-2")

    persisted = json.loads(shot.video_director_plan)["keyframes"][0]
    assert persisted["timed_visual_target"] is True
    assert persisted["image_url"] == "/kf2.png"
    assert persisted["image_task_id"] == "task-2"
