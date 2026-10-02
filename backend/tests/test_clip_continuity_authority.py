import json
from types import SimpleNamespace

import pytest

from app.services import clip_planner


RAW_DESCRIPTION = "皇帝开口询问，侍从回答后故事继续"
RAW_VIDEO_DESCRIPTION = "两人继续交谈，镜头保持同一房间"
EXACT_DIALOGUE = "城门可曾关闭？"


def _shot(
    tmp_path,
    *,
    continuity_mode="NORMAL",
    dialogues=None,
    states=None,
    transitions=None,
):
    shot_image = tmp_path / "shot.png"
    shot_image.write_bytes(b"shot")
    states = states or [
        {"index": 1, "role": "START", "time_seconds": 0, "description": None, "timed_visual_target": False},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 6, "description": "侍从把奏折递到桌案中央", "timed_visual_target": False},
        {"index": 3, "role": "END", "time_seconds": 12, "description": "皇帝独立坐在新的正面构图中", "timed_visual_target": False},
    ]
    transitions = transitions or [
        {"from_keyframe_index": 1, "to_keyframe_index": 2, "start_time": 0, "end_time": 6, "transition_description": "侍从向前移动奏折"},
        {"from_keyframe_index": 2, "to_keyframe_index": 3, "start_time": 6, "end_time": 12, "transition_description": "镜头切到皇帝正面中景"},
    ]
    return SimpleNamespace(
        id="continuity-shot",
        chapter_id="continuity-chapter",
        duration=12,
        continuity_mode=continuity_mode,
        description=RAW_DESCRIPTION,
        video_description=RAW_VIDEO_DESCRIPTION,
        characters=json.dumps(["皇帝", "侍从"], ensure_ascii=False),
        scene="大殿",
        props=json.dumps(["奏折"], ensure_ascii=False),
        dialogues=json.dumps(dialogues or [], ensure_ascii=False),
        image_url=str(shot_image),
        image_path=str(shot_image),
        keyframes="[]",
        video_director_plan=json.dumps({
            "canonical_visual_plan": True,
            "keyframes": states,
            "transitions": transitions,
        }, ensure_ascii=False),
    )


def _fake_planner(monkeypatch, response, captured):
    class FakePromptTemplateService:
        def __init__(self, _db):
            pass

        def get_default_system_template(self, _name):
            return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": json.dumps({"clips": response}, ensure_ascii=False)}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)


async def _plan(monkeypatch, shot, response):
    captured = {}
    _fake_planner(monkeypatch, response, captured)
    temporal_anchors = []
    clips, validation = await clip_planner.plan_clips(
        None,
        SimpleNamespace(id="novel"),
        shot,
        temporal_anchors,
    )
    return clips, validation, temporal_anchors, json.loads(captured["user_content"])


def test_clip_planner_input_projects_only_visual_context_and_speech_intervals(tmp_path):
    dialogues = [{
        "dialogue_id": "D1",
        "character_name": "皇帝",
        "text": EXACT_DIALOGUE,
        "start_time": 1.0,
        "end_time": 4.0,
    }]
    payload = clip_planner.build_clip_planner_input(_shot(tmp_path, dialogues=dialogues), [])
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["shot"] == {
        "id": "continuity-shot",
        "duration": 12,
        "continuity_mode": "NORMAL",
        "characters": ["皇帝", "侍从"],
        "scene": "大殿",
        "props": ["奏折"],
    }
    assert payload["speech_timing_intervals"] == [{
        "event_id": "D1",
        "start_time": 1.0,
        "end_time": 4.0,
    }]
    assert len(payload["visual_state_candidates"]) == 3
    assert len(payload["transition_context"]) == 2
    assert "capabilities" not in payload
    assert "official_dialogue_timeline" not in payload
    assert "temporal_anchors" not in payload
    for forbidden in (RAW_DESCRIPTION, RAW_VIDEO_DESCRIPTION, EXACT_DIALOGUE, '"speaker"', '"dialogues"'):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_t02_dialogue_boundary_with_object_handoff_preserves_visual_continuous(tmp_path, monkeypatch):
    shot = _shot(tmp_path, dialogues=[{
        "dialogue_id": "D1", "character_name": "皇帝", "text": EXACT_DIALOGUE,
        "start_time": 1.0, "end_time": 6.0,
    }])
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE", "reason": "initial visual setup"},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": "CONTINUOUS", "reason": "the object handoff and hand positions continue from the actual prior ending"},
    ]

    clips, validation, _, llm_payload = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert clips[1]["continuity_to_previous"] == "CONTINUOUS"
    assert clips[1]["capability"] == "EXTEND"
    assert clips[1]["previous_clip_index"] == 1
    assert llm_payload["speech_timing_intervals"][0] == {"event_id": "D1", "start_time": 1.0, "end_time": 6.0}


@pytest.mark.asyncio
async def test_t03_dialogue_end_and_story_continuity_preserve_visual_cut(tmp_path, monkeypatch):
    shot = _shot(tmp_path, dialogues=[{
        "dialogue_id": "D1", "character_name": "皇帝", "text": EXACT_DIALOGUE,
        "start_time": 1.0, "end_time": 6.0,
    }])
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE"},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": "CUT", "reason": "independently grounded exterior setup"},
    ]

    clips, validation, _, _ = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert clips[1]["continuity_to_previous"] == "CUT"
    assert clips[1]["capability"] == "GENERATE"
    assert clips[1]["previous_clip_index"] is None
    assert clips[1]["carry_in_state_index"] == 2


@pytest.mark.asyncio
async def test_t08_no_dialogue_spatial_dependency_preserves_continuous(tmp_path, monkeypatch):
    shot = _shot(tmp_path, dialogues=[], transitions=[
        {"from_keyframe_index": 1, "to_keyframe_index": 2, "start_time": 0, "end_time": 6, "transition_description": "人物从庭院持续走入回廊"},
        {"from_keyframe_index": 2, "to_keyframe_index": 3, "start_time": 6, "end_time": 12, "transition_description": "保持运动方向走到门口"},
    ])
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE"},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": "CONTINUOUS", "reason": "walking direction and body trajectory depend on the prior ending"},
    ]

    clips, validation, _, llm_payload = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert llm_payload["speech_timing_intervals"] == []
    assert clips[1]["continuity_to_previous"] == "CONTINUOUS"
    assert clips[1]["capability"] == "EXTEND"


@pytest.mark.asyncio
async def test_t09_no_dialogue_timed_continuous_state_derives_temporal_requirement(tmp_path, monkeypatch):
    timed_image = tmp_path / "timed.png"
    timed_image.write_bytes(b"timed")
    states = [
        {"index": 1, "role": "START", "time_seconds": 0, "description": None, "timed_visual_target": False},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 6, "description": "骑者持续前行", "timed_visual_target": False},
        {"index": 3, "role": "INTERMEDIATE", "time_seconds": 9, "description": "骑者回头", "timed_visual_target": True, "image_url": str(timed_image)},
        {"index": 4, "role": "END", "time_seconds": 12, "description": "骑者拔剑", "timed_visual_target": False},
    ]
    shot = _shot(tmp_path, dialogues=[], states=states)
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE"},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": "CONTINUOUS", "reason": "rider motion continues from prior ending"},
    ]

    clips, validation, anchors, _ = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert clips[1]["continuity_to_previous"] == "CONTINUOUS"
    assert clips[1]["requires_temporal_control"] is True
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"
    assert clips[1]["selected_temporal_target_ids"] == ["KF3"]
    assert [item["source"]["id"] for item in anchors] == ["KF3"]


@pytest.mark.asyncio
async def test_same_scene_same_people_same_conversation_can_be_cut_under_continuous_take(tmp_path, monkeypatch):
    shot = _shot(tmp_path, continuity_mode="CONTINUOUS_TAKE", dialogues=[{
        "dialogue_id": "D1", "character_name": "皇帝", "text": EXACT_DIALOGUE,
        "start_time": 1.0, "end_time": 10.0,
    }])
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE"},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": "CUT", "reason": "new independently grounded frontal composition"},
    ]

    clips, validation, _, llm_payload = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert llm_payload["shot"]["continuity_mode"] == "CONTINUOUS_TAKE"
    assert clips[1]["continuity_to_previous"] == "CUT"
    assert clips[1]["capability"] == "GENERATE"


@pytest.mark.asyncio
async def test_llm_payload_excludes_physical_and_legacy_execution_authority(tmp_path, monkeypatch):
    shot = _shot(tmp_path)
    response = [{"clip_index": 1, "start_time": 0, "end_time": 12, "continuity_to_previous": "NONE"}]

    _, validation, _, llm_payload = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert "available_generation_inputs" not in llm_payload
    assert "capabilities" not in llm_payload
    assert "temporal_anchors" not in llm_payload
    serialized = json.dumps(llm_payload, ensure_ascii=False)
    for forbidden in (
        "SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME", "supported_frame_counts",
        "picture_index", "previous_task_id", "workflow_id", "reference_manifest",
    ):
        assert forbidden not in serialized
