import json
from types import SimpleNamespace

import pytest

from app.services import video_director_ai


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selected_mode", "expected_task_type"),
    [
        ("SINGLE_FRAME", "h3_single_frame_prompt"),
        ("FIRST_LAST_FRAME", "h3_first_last_frame_prompt"),
        ("MULTI_KEYFRAME", "h3_multi_keyframe_prompt"),
    ],
)
async def test_h3_prompt_excludes_generated_clip_data(monkeypatch, selected_mode, expected_task_type):
    captured = {}

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": "camera moves forward"}

    monkeypatch.setattr(video_director_ai, "LLMService", FakeLLMService)
    monkeypatch.setattr(
        video_director_ai,
        "resolve_prompt_template",
        lambda *_args: SimpleNamespace(template="system", name="template"),
    )

    clip = {
        "clip_index": 1,
        "start_time": 0,
        "end_time": 4,
        "prompt_text": "old prompt",
        "video_url": "https://example.com/video.mp4",
        "local_path": "/tmp/video.mp4",
        "source_video_url": "https://example.com/source.mp4",
        "generated_at": "2026-09-22T00:00:00",
        "generated_by_task_id": "task-id",
    }
    shot = SimpleNamespace(
        id="shot-id",
        index=2,
        chapter_id="chapter-id",
        description="description",
        video_description="video description",
        duration=4,
        continuity_mode="NORMAL",
        characters="[]",
        scene="scene",
        props="[]",
        dialogues="[]",
        video_director_plan=None,
    )
    db = SimpleNamespace(commit=lambda: None)
    novel = SimpleNamespace(id="novel-id")

    await video_director_ai.build_h3_video_prompt(
        db=db,
        novel=novel,
        shot=shot,
        selected_mode=selected_mode,
        clip=clip,
        workflow_capability={},
        workflow_type="video",
        workflow_name="workflow",
        start_image_url=None,
        keyframes=[],
        transitions=[],
        clip_dialogues=[],
        reference_images=[],
    )

    payload = json.loads(captured["user_content"].split("\n\n", 1)[1])
    assert payload["clip"] == {"clip_index": 1, "start_time": 0, "end_time": 4}
    assert captured["task_type"] == expected_task_type
    assert clip["prompt_text"] == "old prompt"


@pytest.mark.asyncio
async def test_multi_keyframe_payload_derives_silent_characters_and_visual_only_transitions(monkeypatch):
    captured = {}

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "content": "百姓1 performs assigned dialogue D1. 百姓2、皇帝、群臣1、群臣2 remain silent.",
            }

    monkeypatch.setattr(video_director_ai, "LLMService", FakeLLMService)
    monkeypatch.setattr(
        video_director_ai,
        "resolve_prompt_template",
        lambda *_args: SimpleNamespace(template="system", name="template"),
    )

    shot = SimpleNamespace(
        id="shot-5",
        index=5,
        chapter_id="chapter-id",
        description="百姓注视皇帝",
        video_description="",
        duration=4,
        continuity_mode="NORMAL",
        characters=json.dumps(["百姓1", "百姓2", "皇帝", "群臣1", "群臣2"], ensure_ascii=False),
        scene="街道",
        props="[]",
        dialogues="[]",
        video_director_plan=None,
    )
    db = SimpleNamespace(commit=lambda: None)

    await video_director_ai.build_h3_video_prompt(
        db=db,
        novel=SimpleNamespace(id="novel-id"),
        shot=shot,
        selected_mode="MULTI_KEYFRAME",
        clip={"clip_index": 1, "start_time": 0, "end_time": 4},
        workflow_capability={},
        workflow_type="three_frame_video",
        workflow_name="workflow",
        start_image_url=None,
        keyframes=[],
        transitions=[{
            "transition_description": (
                "百姓1持续对身旁的百姓2低声说话；百姓2侧耳倾听；"
                "所有人物在该过渡全过程保持沉默，不说话、不低语、不发出人物语音；"
                "只保留必要的环境声和动作声。"
            ),
        }],
        clip_dialogues=[{
            "speaker": "百姓1",
            "text": "他确实没穿衣服……",
            "start_time": 1.0,
            "end_time": 3.99,
        }],
        reference_images=[],
    )

    payload = json.loads(captured["user_content"].split("\n\n", 1)[1])
    assert payload["silent_characters"] == ["百姓2", "皇帝", "群臣1", "群臣2"]
    assert payload["dialogue_timeline_source"][0]["speaker"] == "百姓1"
    assert payload["dialogue_timeline_source"][0]["start_time"] == 1.0
    assert payload["dialogue_timeline_source"][0]["end_time"] == 3.99

    transition_text = payload["transitions"][0]["transition_description"]
    assert "嘴巴微张，表现低声交谈的视觉状态" in transition_text
    assert "百姓2侧耳倾听" in transition_text
    for forbidden in ("保持沉默", "不说话", "不低语", "不发出人物语音", "只保留必要的环境声"):
        assert forbidden not in transition_text
        assert forbidden not in payload["motion_directive"]
