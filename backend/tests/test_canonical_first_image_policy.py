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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,shared_appearance,required_rules",
    [
        pytest.param("A戴帽", "A和B都戴帽", (
            "正式角色参考中 A 和 B 都戴帽，canonical 只说 A 戴帽",
            "不得写成只有 A 戴帽或 B 不得戴帽",
        ), id="A-shared-hats"),
        pytest.param("A提箱子", "A和B各有箱子", (
            "A 和 B 各有箱子，canonical 只说 A 提箱子",
            "不得写成箱子仅属于 A，也不得禁止 B 持有另一个箱子",
        ), id="B-shared-boxes"),
        pytest.param("A穿红色衣服", "A和B都穿红色衣服", (
            "A 穿红色不能推出红色是 A 独有",
        ), id="shared-color"),
        pytest.param("只有A戴帽，B未戴帽", "A和B都戴帽", (
            "canonical 明确说只有 A 戴帽、B 未戴帽",
            "必须表达并执行这些当前状态",
        ), id="C-explicit-exclusivity"),
        pytest.param("B摘下帽子", "A和B都戴帽", (
            "B 摘下帽子",
            "不得用共享外观或连续性保留被明确取消的属性",
        ), id="D-explicit-removal"),
        pytest.param("A戴帽，A已靠近B并站在B前方，身体和双脚转向门内，摄影机推进", "A和B都戴帽", (
            "本规则不改变 Canonical-First、Material Delta Rule",
            "必须纠正物理图中的冲突",
            "人物靠近、前后站位变化、身体或双脚转向",
            "摄影机推进或拉远或换构图",
        ), id="E-spatial-delta-with-shared-appearance"),
    ],
)
async def test_positive_facts_do_not_invent_exclusivity_contract(
    db_session, target, shared_appearance, required_rules,
):
    # Inspect instructions and unchanged inputs, not a mock's supposed reasoning.
    # Formal images are represented by the same A/B identity manifest; their
    # pixels are not interpreted by this text-only builder contract test.
    prompt, payload = await capture_builder(
        db_session, target, [TEMPORAL, CHARACTER], previous_description=shared_appearance,
    )
    assert payload["previous_keyframe"]["description"] == shared_appearance
    assert payload["reference_image_manifest"] == [TEMPORAL, CHARACTER]
    for rule in (
        "Positive fact does not imply exclusivity.",
        "关于一个角色的正向事实，不能自动变成其他角色的负向约束",
        "只有 current canonical state 或正式资产在其权威职责内明确提供排他事实时",
        "道具的持有者或归属描述本身不证明 exclusive ownership",
        "不得为了角色区分而发明独占服装、颜色、配饰或道具",
        "不得因 canonical 只提到 A 的某项外观，就删除 B 已有的合法同类外观",
        *required_rules,
    ):
        assert rule in prompt
    # Shared attributes cannot relax the actor/prop closure or swap identities.
    assert "不得复制已有角色" in prompt
    assert "不得把角色 A 的脸/服装/发型变成 B" in prompt
    assert "道具身份由 shot.props + prop_asset_bindings 定义" in prompt
    assert "只出现 shot.props 中当前关键帧实际可见的剧情道具" in prompt
