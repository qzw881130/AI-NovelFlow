from app.models.novel import Novel, Prop
from app.services.prompt_builder import build_character_prompt, build_prop_prompt, build_scene_prompt
from app.services.prop_image_service import PropService
from app.services.prop_policy import (
    PROP_EXISTENCE_NONEXISTENT,
    PROP_EXISTENCE_REAL,
    get_visual_prop_names,
    normalize_prop_existence,
)


def test_prop_prompt_enforces_prop_only_even_when_name_contains_character():
    prompt = build_prop_prompt(
        name="皇帝的新衣",
        appearance="骗子声称献给皇帝的华丽衣服",
        description="皇帝穿上它参加游行",
        template="{name}, {appearance}, {description}",
        style="欧洲童话风格",
    )

    assert "画面唯一主体必须是当前道具本身" in prompt
    assert "禁止出现任何人物" in prompt
    assert "禁止真人、角色或人体模特穿戴" in prompt
    assert "背景只能是均匀、纯色、无纹理、无空间语义的中性底色" in prompt
    assert "禁止生成房间、建筑、墙面、地面、门窗、台面、展台、展示柜、箱柜、家具、布景、风景、环境光源、环境阴影或任何其他道具" in prompt
    assert "NO ENVIRONMENT. NO ROOM. NO WALL. NO FLOOR. NO TABLE. NO PEDESTAL" in prompt
    assert "原材料不得生成成由其制成的成品" in prompt
    assert "PROP ONLY" in prompt
    assert "纯道具资产图约束" not in build_character_prompt("皇帝", "欧洲皇帝", template="{appearance}")
    assert "纯道具资产图约束" not in build_scene_prompt("广场", "石砌广场", template="{setting}")

    material_prompt = build_prop_prompt(
        name="绸缎",
        appearance="一卷未经裁剪和缝制的紫色丝绸布匹",
        template="{name}, {appearance}",
    )
    assert "布料不得变成服装" in material_prompt
    assert "RAW MATERIAL MUST NOT BECOME A FINISHED PRODUCT" in material_prompt


def test_standard_prop_template_uses_an_isolated_plain_background():
    from pathlib import Path

    template = (Path(__file__).resolve().parents[1] / "prompt_templates" / "prop.txt").read_text(encoding="utf-8")

    assert "isolated object asset sheet" in template
    assert "plain solid neutral background" in template
    assert "no environmental context" in template
    assert "背景只能是均匀、纯色、无纹理、无空间语义的中性底色" in template
    assert "NO ENVIRONMENT. NO ROOM. NO WALL. NO FLOOR. NO TABLE. NO PEDESTAL" in template
    assert "product photography" not in template


def test_prop_existence_normalizes_explicit_and_textual_nonexistence():
    assert normalize_prop_existence("REAL", "实际上并不存在") == PROP_EXISTENCE_REAL
    assert normalize_prop_existence("FICTIONAL_OR_NONEXISTENT") == PROP_EXISTENCE_NONEXISTENT
    assert normalize_prop_existence(None, "骗子声称有这种布料，但实际上并不存在") == PROP_EXISTENCE_NONEXISTENT
    assert normalize_prop_existence(None, "一台真实使用的木制织机") == PROP_EXISTENCE_REAL


def test_nonexistent_prop_is_blocked_from_generation_and_visual_resolution(db_session):
    novel = Novel(title="皇帝的新装")
    db_session.add(novel)
    db_session.commit()
    real_prop = Prop(novel_id=novel.id, name="织机", existence=PROP_EXISTENCE_REAL)
    fictional_prop = Prop(
        novel_id=novel.id,
        name="皇帝的新衣",
        description="实际上并不存在",
        existence=PROP_EXISTENCE_NONEXISTENT,
    )
    db_session.add_all([real_prop, fictional_prop])
    db_session.commit()

    result = PropService(db_session).create_prop_image_task(fictional_prop.id)

    assert result == {"success": False, "message": "该道具在故事中不存在，不能生成实体参考图"}
    assert get_visual_prop_names(
        db_session,
        novel.id,
        ["皇帝的新衣", "织机"],
    ) == ["织机"]
