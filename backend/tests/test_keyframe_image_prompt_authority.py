import json
from types import SimpleNamespace

import pytest

from app.models.novel import Chapter, Novel, Prop
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.services.shot_keyframe_service import ShotKeyframeService


RAW_DESCRIPTION = "皇帝开口询问，侍从回答"
RAW_VIDEO_DESCRIPTION = "皇帝正在说话，侍从听完回答"
EXACT_DIALOGUE = "朕问你，城门可曾关闭？"
TARGET_VISUAL_STATE = "侍从身体微微前倾，视线朝向皇帝；皇帝眉头微皱，嘴角略向下"


def _fixture(db_session, *, dialogues, template_text="只根据 current_keyframe 渲染可见状态"):
    template = PromptTemplate(
        name="test #09 override",
        type="keyframe_image_prompt",
        template=template_text,
        is_system=False,
        is_active=True,
    )
    db_session.add(template)
    db_session.flush()
    novel = Novel(title="#09 authority", keyframe_image_prompt_template_id=template.id)
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="殿前")
    prop = Prop(novel_id=novel.id, name="奏折", existence="REAL")
    db_session.add_all([chapter, prop])
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description=RAW_DESCRIPTION,
        video_description=RAW_VIDEO_DESCRIPTION,
        characters=json.dumps(["皇帝", "侍从"], ensure_ascii=False),
        scene="大殿",
        props=json.dumps(["奏折"], ensure_ascii=False),
        duration=8,
        continuity_mode="CONTINUOUS_TAKE",
        dialogues=json.dumps(dialogues, ensure_ascii=False),
        video_director_plan="{}",
    )
    db_session.add(shot)
    db_session.commit()
    return novel, shot


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dialogues",
    [
        [],
        [{"character_name": "皇帝", "text": EXACT_DIALOGUE, "start_time": 1.0, "end_time": 3.0}],
    ],
)
async def test_canonical_keyframe_prompt_projects_only_visual_authority_and_context(db_session, dialogues):
    novel, shot = _fixture(db_session, dialogues=dialogues)
    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return {"success": True, "content": TARGET_VISUAL_STATE}

    service = ShotKeyframeService()
    service.llm_service = SimpleNamespace(chat_completion=complete)
    current = {
        "index": 3,
        "frame_index": 2,
        "plan_keyframe_index": 3,
        "role": "INTERMEDIATE",
        "time_seconds": 5.0,
        "description": TARGET_VISUAL_STATE,
        "timed_visual_target": True,
        "prompt_text": "stale prompt must not be projected",
        "image_url": "/api/files/current.png",
    }
    previous = {
        "index": 2,
        "plan_keyframe_index": 2,
        "role": "INTERMEDIATE",
        "time_seconds": 2.0,
        "description": "侍从直立，双手托住奏折",
        "image_url": "/api/files/previous.png",
        "prompt_text": "old prompt",
    }
    manifest = [{
        "picture": 1,
        "picture_index": 1,
        "kind": "CHARACTER_IDENTITY",
        "type": "CHARACTER_IDENTITY",
        "sources": ["CHAR:皇帝", "CHAR:侍从"],
        "purpose": "支持皇帝询问、侍从回答时的嘴型",
        "url": "/api/files/characters.png",
        "path": "/tmp/characters.png",
    }]

    prompt = await service._build_qwen_keyframe_prompt(
        db_session,
        novel,
        shot,
        current,
        previous,
        SimpleNamespace(current_step=""),
        reference_manifest=manifest,
    )

    payload = json.loads(captured["user_content"].split("\n\n", 1)[1])
    serialized = json.dumps(payload, ensure_ascii=False)
    assert set(payload["shot"]) == {"id", "index", "characters", "scene", "props"}
    assert payload["shot"]["characters"] == ["皇帝", "侍从"]
    assert payload["shot"]["scene"] == "大殿"
    assert payload["shot"]["props"] == ["奏折"]
    assert payload["current_keyframe"]["description"] == TARGET_VISUAL_STATE
    assert payload["current_keyframe"]["timed_visual_target"] is True
    assert payload["previous_keyframe"]["description"] == "侍从直立，双手托住奏折"
    assert payload["reference_image_manifest"] == [{
        "picture": 1,
        "picture_index": 1,
        "kind": "CHARACTER_IDENTITY",
        "type": "CHARACTER_IDENTITY",
        "sources": ["CHAR:皇帝", "CHAR:侍从"],
    }]
    for forbidden in (
        RAW_DESCRIPTION,
        RAW_VIDEO_DESCRIPTION,
        EXACT_DIALOGUE,
        "character_name",
        "start_time",
        "end_time",
        "dialogue_timeline",
        "支持皇帝询问、侍从回答时的嘴型",
        "stale prompt must not be projected",
    ):
        assert forbidden not in serialized
    assert prompt == TARGET_VISUAL_STATE


@pytest.mark.asyncio
async def test_novel_override_cannot_recover_forbidden_keyframe_prompt_sources(db_session):
    novel, shot = _fixture(
        db_session,
        dialogues=[{"character_name": "皇帝", "text": EXACT_DIALOGUE, "start_time": 1, "end_time": 2}],
        template_text=(
            "旧版 override：读取 shot.description、shot.video_description、shot.dialogues，"
            "无台词时要求 closed mouth。"
        ),
    )
    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return {"success": True, "content": "侍从身体微微前倾，视线朝向皇帝"}

    service = ShotKeyframeService()
    service.llm_service = SimpleNamespace(chat_completion=complete)
    await service._build_qwen_keyframe_prompt(
        db_session,
        novel,
        shot,
        {"index": 2, "role": "END", "time_seconds": 8, "description": "侍从身体微微前倾，视线朝向皇帝"},
        None,
        SimpleNamespace(current_step=""),
        reference_manifest=[],
    )

    assert "旧版 override" in captured["system_prompt"]
    for forbidden in (RAW_DESCRIPTION, RAW_VIDEO_DESCRIPTION, EXACT_DIALOGUE, "dialogues", "speaker", "dialogue_timeline"):
        assert forbidden not in captured["user_content"]


@pytest.mark.asyncio
async def test_keyframe_image_prompt_output_rejects_explicit_speech_authority(db_session):
    novel, shot = _fixture(db_session, dialogues=[])

    async def complete(**_kwargs):
        return {"success": True, "content": "侍从正在回答皇帝，嘴唇张开"}

    service = ShotKeyframeService()
    service.llm_service = SimpleNamespace(chat_completion=complete)
    with pytest.raises(ValueError, match="KEYFRAME_IMAGE_PROMPT_SPEECH_AUTHORITY_VIOLATION"):
        await service._build_qwen_keyframe_prompt(
            db_session,
            novel,
            shot,
            {"index": 2, "role": "END", "time_seconds": 8, "description": "侍从身体微微前倾，视线朝向皇帝"},
            None,
            SimpleNamespace(current_step=""),
            reference_manifest=[],
        )


@pytest.mark.asyncio
async def test_previous_visual_state_cannot_supply_speech_authority(db_session):
    novel, shot = _fixture(db_session, dialogues=[])
    service = ShotKeyframeService()
    service.llm_service = SimpleNamespace(chat_completion=None)

    with pytest.raises(ValueError, match="KEYFRAME_IMAGE_INPUT_SPEECH_AUTHORITY_VIOLATION"):
        await service._build_qwen_keyframe_prompt(
            db_session,
            novel,
            shot,
            {"index": 3, "role": "END", "time_seconds": 8, "description": "侍从身体微微前倾"},
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 4, "description": "侍从正在回答皇帝"},
            SimpleNamespace(current_step=""),
            reference_manifest=[],
        )


@pytest.mark.asyncio
async def test_keyframe_prompt_fallback_never_recovers_raw_shot_narrative(db_session):
    novel = Novel(title="fallback")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="chapter")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description=RAW_DESCRIPTION,
        video_description=RAW_VIDEO_DESCRIPTION,
        characters="[]",
        scene="",
        props="[]",
        dialogues="[]",
    )
    db_session.add(shot)
    db_session.commit()

    service = ShotKeyframeService()
    # No template is installed in this isolated session; exercise the deterministic fallback.
    prompt = await service._build_qwen_keyframe_prompt(
        db_session,
        novel,
        shot,
        {"index": 2, "description": "皇帝眉头微皱，嘴角略向下"},
        None,
        SimpleNamespace(current_step=""),
        reference_manifest=[],
    )
    assert "皇帝眉头微皱，嘴角略向下" in prompt
    assert RAW_DESCRIPTION not in prompt
    assert RAW_VIDEO_DESCRIPTION not in prompt
