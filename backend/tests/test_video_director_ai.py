import json
from types import SimpleNamespace

import pytest

from app.services import video_director_ai


def test_silent_character_audit_accepts_non_vocal_subject_mapping():
    prompt = """subject_definitions:
<Subject 1> is 老大臣, an elderly court official.
summary:
<Subject 1> remains non-vocal throughout the entire clip.
"""

    audit = video_director_ai._audit_final_h3_prompt(prompt, [], ["老大臣"])

    assert audit["passed"]
    assert "SILENT_CHARACTER_CONSTRAINT_MISSING" not in audit["issues"]


def test_clip_visible_characters_come_from_selected_keyframes():
    keyframes = [{
        "index": 3,
        "description": "Scene: corridor\nCharacters:\n- 老大臣: stands at the door\nAction: prepares to knock",
    }]

    assert video_director_ai._clip_visible_characters(keyframes, ["老大臣", "骗子1", "骗子2"]) == ["老大臣"]


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


@pytest.mark.asyncio
async def test_projected_clip_dialogues_reappear_as_exact_chinese_text_in_h3_prompt(monkeypatch):
    captured = {}

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": "camera follows the assigned dialogue."}

    monkeypatch.setattr(video_director_ai, "LLMService", FakeLLMService)
    monkeypatch.setattr(
        video_director_ai,
        "resolve_prompt_template",
        lambda *_args: SimpleNamespace(template="system", name="template"),
    )

    text = "陛下，宫中最好的金丝库存……"
    shot = SimpleNamespace(
        id="shot-17",
        index=17,
        chapter_id="chapter-id",
        description="皇帝与宫廷总管对话",
        video_description="",
        duration=28,
        continuity_mode="NORMAL",
        characters='["皇帝", "宫廷总管"]',
        scene="宫殿",
        props="[]",
        dialogues="[]",
        video_director_plan=None,
    )
    clip_dialogues = [{
        "dialogue_id": "D7",
        "character_name": "宫廷总管",
        "text": text,
        "start_time": 14.2,
        "end_time": 15.0,
        "local_start_time": 14.2,
        "local_end_time": 15.0,
        "projected_duration": 0.8,
        "dialogue_timing_source": "official",
        "projection_mode": "intersection",
    }]

    final_prompt = await video_director_ai.build_h3_video_prompt(
        db=SimpleNamespace(commit=lambda: None),
        novel=SimpleNamespace(id="novel-id"),
        shot=shot,
        selected_mode="MULTI_KEYFRAME",
        clip={"clip_index": 1, "start_time": 0, "end_time": 15},
        workflow_capability={},
        workflow_type="video",
        workflow_name="workflow",
        start_image_url=None,
        keyframes=[],
        transitions=[],
        clip_dialogues=clip_dialogues,
        reference_images=[],
    )

    assert text in final_prompt
    assert "No assigned dialogue" not in final_prompt
    payload = json.loads(captured["user_content"].split("\n\n", 1)[1])
    assert payload["dialogue_timeline_source"][0]["id"] == "D7"
    assert payload["dialogue_timeline_source"][0]["duration"] == 0.8


@pytest.mark.asyncio
async def test_shot17_single_canonical_speech_authority(monkeypatch):
    texts = [
        "你们需要什么？", "最上等的金丝。", "还有最柔软的丝绸。",
        "越多越好。", "除此之外，还需要一间安静、宽敞而明亮的织造室。", "都给他们。",
    ]
    speakers = ["皇帝", "高个骗子", "矮个骗子", "高个骗子", "矮个骗子", "皇帝"]
    times = [(1, 2.5), (2.7, 4.2), (4.4, 6.4), (6.6, 7.6), (7.8, 12.8), (13, 14)]

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": """subject_definitions:
<Subject 1> is 皇帝, the ruler.
<Subject 2> is 高个骗子, the taller visitor.
<Subject 3> is 矮个骗子, the shorter visitor.
<Subject 4> is 宫廷总管, a court official.
summary:
The visitors face the ruler; the camera moves gently.
dialogue_timeline:
D4: <Subject 3> speaks from 6.6s to 7.6s. exact_dialogue: “越多越好。”
detailed_description:
Picture 1 to Picture 2: <Subject 2> stands upright and watches <Subject 1>.
Picture 2 to Picture 3: <Subject 3> shifts gaze toward <Subject 1>.
overall_soundscape:
Room tone and footsteps accompany assigned dialogue D1-D6."""}

    monkeypatch.setattr(video_director_ai, "LLMService", FakeLLMService)
    monkeypatch.setattr(video_director_ai, "resolve_prompt_template", lambda *_: SimpleNamespace(template="system", name="template"))
    shot = SimpleNamespace(
        id="shot-17", index=17, chapter_id="chapter-id", description="皇帝面对骗子",
        video_description="", duration=28, continuity_mode="NORMAL",
        characters=json.dumps([*dict.fromkeys(speakers), "宫廷总管"], ensure_ascii=False),
        scene="宫殿", props="[]", dialogues="[]", video_director_plan=None,
    )
    dialogues = [
        {"dialogue_id": f"D{i}", "character_name": speaker, "text": f"“{text}”",
         "start_time": start, "end_time": end, "local_start_time": start, "local_end_time": end,
         "projection_mode": "intersection"}
        for i, (speaker, text, (start, end)) in enumerate(zip(speakers, texts, times), 1)
    ]
    prompt = await video_director_ai.build_h3_video_prompt(
        db=SimpleNamespace(commit=lambda: None), novel=SimpleNamespace(id="novel-id"), shot=shot,
        selected_mode="MULTI_KEYFRAME", clip={"clip_index": 1, "start_time": 0, "end_time": 14.2},
        workflow_capability={}, workflow_type="three_frame_video", workflow_name="workflow",
        start_image_url=None, keyframes=[], transitions=[], clip_dialogues=dialogues,
        reference_images=[],
    )

    assert prompt.count("dialogue_timeline:") == 1
    for i, (text, subject, (start, end)) in enumerate(zip(texts, [1, 2, 3, 2, 3, 1], times), 1):
        assert prompt.count(text) == 1
        assert f"D{i}:\n  speaker: <Subject {subject}>\n  start_time: {float(start)}s\n  end_time: {float(end)}s\n  exact_dialogue: {text}" in prompt
    assert 'exact_dialogue: "' not in prompt
    assert "<Subject 3> speaks from 6.6s" not in prompt
    assert "silent_characters: <Subject 4>" in prompt


def test_conflicting_subject_mapping_is_not_used_as_speech_authority():
    with pytest.raises(ValueError, match="Subject mapping conflicts"):
        video_director_ai._subject_bindings(
            "subject_definitions:\n<Subject 2> is 皇帝, the ruler.", ["皇帝", "高个骗子"]
        )
