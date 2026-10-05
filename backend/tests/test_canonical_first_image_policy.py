"""Inspect runtime #09 instructions/payloads; mocks do not prove model compliance."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.novel import Chapter, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.services.prompt_template_service import PromptTemplateService
from app.services.shot_keyframe_service import ShotKeyframeService


PROMPT_FILE = Path(__file__).resolve().parents[1] / "prompt_templates" / "09_NovelFlow_QwenEdit2511_KeyframeImagePrompt_V1.txt"
TEMPORAL = {
    "picture": 1, "picture_index": 1, "kind": "TEMPORAL_ANCHOR",
    "type": "TEMPORAL_ANCHOR", "sources": ["KF2"],
}
CHARACTER = {
    "picture": 2, "picture_index": 2, "kind": "CHARACTER_IDENTITY",
    "type": "CHARACTER_IDENTITY", "sources": ["CHAR:A", "CHAR:B"], "composed": True,
}


async def capture_builder(db, target, manifest, previous_description="A在B后方直立，身体朝外"):
    PromptTemplateService(db).init_system_templates()
    novel = Novel(title="canonical-first contract")
    db.add(novel)
    db.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="contract")
    db.add(chapter)
    db.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description="unused narrative",
                characters='["A", "B"]', scene="room", props="[]", dialogues="[]")
    db.add(shot)
    db.commit()
    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return {"success": True, "content": target}

    service = ShotKeyframeService()
    service.llm_service = SimpleNamespace(chat_completion=complete)
    await service._build_qwen_keyframe_prompt(
        db, novel, shot,
        {"index": 3, "role": "INTERMEDIATE", "time_seconds": 8, "description": target},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 4, "description": previous_description},
        SimpleNamespace(current_step=""), reference_manifest=manifest,
    )
    assert captured["system_prompt"] == PROMPT_FILE.read_text()
    payload = json.loads(captured["user_content"].split("\n\n", 1)[1])
    assert payload["current_keyframe"]["description"] == target
    return captured["system_prompt"], payload


@pytest.mark.asyncio
async def test_current_position_overrides_selected_temporal_layout(db_session):
    prompt, payload = await capture_builder(db_session, "A已靠近B，A在前、B在后", [TEMPORAL])
    assert payload["reference_image_manifest"] == [TEMPORAL]
    assert "人物位置、blocking、空间关系" in prompt
    assert "必须纠正物理图中的冲突" in prompt
    assert "不能假设物理参考已正确实现它" in prompt
    for obsolete in ("上一关键帧通常是当前编辑的 canvas", "当前编辑最重要的连续性基础",
                     "和上一关键帧为准", "以主分镜图和"):
        assert obsolete not in prompt


@pytest.mark.asyncio
async def test_current_pose_and_orientation_override_temporal_pose(db_session):
    prompt, _ = await capture_builder(db_session, "A身体半转朝内，双脚朝向室内，表情紧张", [TEMPORAL])
    assert "姿态、身体与双脚朝向、动作阶段、表情" in prompt
    assert "Material Delta Rule" in prompt
    assert "身体或双脚转向" in prompt
    assert "而保留与当前 canonical 冲突的旧状态" in prompt


@pytest.mark.asyncio
async def test_unchanged_identity_and_clothing_keep_continuity(db_session):
    prompt, _ = await capture_builder(db_session, "A向B靠近，保持既有服装", [TEMPORAL, CHARACTER])
    assert "支持身份连续性、未变化服装、环境、道具" in prompt
    assert "canonical 没有要求改变且不与当前目标冲突的身份、服装、环境、道具与连续性事实" in prompt
    assert "保持 controlled transformation" in prompt
    assert "不得复制已有角色" in prompt


@pytest.mark.asyncio
async def test_formal_character_defines_who_canonical_defines_where_and_pose(db_session):
    prompt, payload = await capture_builder(db_session, "A在门内侧俯身，B在门外直立", [TEMPORAL, CHARACTER])
    assert payload["reference_image_manifest"][1] == CHARACTER
    assert "Character reference defines WHO; current canonical state defines WHERE / POSE / ACTION." in prompt
    assert "正式角色图不规定当前人物站位、姿态或构图" in prompt
    assert "该图的展示姿态、站位、背景、多视图排版不属于当前剧情构图" in prompt


@pytest.mark.asyncio
async def test_absent_temporal_reference_does_not_invent_a_picture(db_session):
    character = {**CHARACTER, "picture": 1, "picture_index": 1}
    prompt, payload = await capture_builder(db_session, "A在室内直立，B在门外", [character])
    assert payload["reference_image_manifest"] == [character]
    assert "KF2" not in json.dumps(payload["reference_image_manifest"])
    assert "不得使用未提供或未实际传入的参考资产" in prompt
    assert "不得引用 manifest 中不存在的" in prompt


@pytest.mark.asyncio
async def test_multiple_reference_order_and_picture_identity_remain_unchanged(db_session):
    manifest = [
        {**TEMPORAL, "purpose": "old layout must win", "url": "/old.png", "path": "/old.png"},
        CHARACTER,
        {"picture": 3, "picture_index": 3, "kind": "SCENE", "type": "SCENE", "sources": ["SCENE:room"]},
    ]
    before = copy.deepcopy(manifest)
    prompt, payload = await capture_builder(db_session, "A朝内转身，门内纵深进入构图", manifest)
    assert manifest == before
    assert payload["reference_image_manifest"] == [TEMPORAL, CHARACTER, manifest[2]]
    assert "old layout must win" not in json.dumps(payload)
    assert "picture_index=1 对应 <image_1>，picture_index=2 对应 <image_2>，依此类推" in prompt
    assert "不得为了固定槽位传空图片占位" in prompt


def test_existing_system_sync_updates_policy_in_place_and_preserves_override(db_session):
    system = PromptTemplate(id="existing-09", name="视频关键帧生图提示词构建",
                            type="keyframe_image_prompt", template="previous image as canvas", is_system=True)
    override = PromptTemplate(id="custom-09", name="custom policy", type="keyframe_image_prompt",
                              template="user-selected template", is_system=False)
    novel = Novel(title="override", keyframe_image_prompt_template_id=override.id)
    db_session.add_all([system, override, novel])
    db_session.commit()
    PromptTemplateService(db_session).init_system_templates()
    default = PromptTemplateService(db_session).get_default_system_template("keyframe_image_prompt")
    assert default.id == system.id
    assert default.template == PROMPT_FILE.read_text()
    service = ShotKeyframeService()
    assert service._get_keyframe_image_prompt_template(db_session, Novel(title="default")).id == system.id
    assert service._get_keyframe_image_prompt_template(db_session, novel).id == override.id
    assert override.template == "user-selected template"
