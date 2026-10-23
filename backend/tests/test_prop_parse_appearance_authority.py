"""Prop Parser Prompt contract tests; these do not implement an NLP validator."""

from pathlib import Path

from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.services.novel_service import NovelService
from app.services.prompt_template_service import (
    PromptTemplateService,
    SYSTEM_PROP_PARSE_TEMPLATES,
)


PROMPT_FILE = Path(__file__).resolve().parents[1] / "prompt_templates" / "prop_parse.txt"
STANDARD_TEMPLATE_ID = "163f7402-352b-4122-a433-e96f5e1978e7"


def _prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def test_description_may_retain_story_context_without_defining_permanent_appearance():
    prompt = _prompt()

    assert "description 描述该物件在故事中的功能、背景、用途、重要性及相关剧情事实" in prompt
    assert "这些剧情事实不等于该物件的永久视觉外观" in prompt
    assert "两名骗子曾用它藏匿金丝" in prompt
    assert "皇帝赏赐给骗子的大量珍贵织造材料" in prompt
    assert "两名骗子利用它们假装织布" in prompt


def test_bag_appearance_excludes_current_contents_placement_and_scene():
    prompt = _prompt()
    bag_rule = next(line for line in prompt.splitlines() if line.startswith("- 墙角大布袋："))

    assert "一个大型粗麻布袋本身" in bag_rule
    assert "不得把墙角、Scene 背景、当前金丝内容物或藏入后鼓起的状态写成稳定身份" in bag_rule
    assert "当前所在位置、摆放关系、朝向" in prompt
    assert "内容物、空/满/鼓起状态" in prompt
    assert "周围环境、Scene 背景" in prompt


def test_appearance_is_subject_only_and_does_not_design_a_background():
    prompt = _prompt()

    assert "appearance 必须是纯主体描述" in prompt
    for excluded_context in (
        "背景、环境、房间、墙面、地面、台面、展台、容器、陈列空间",
        "周围物件、环境光源或场景氛围",
    ):
        assert excluded_context in prompt
    assert "背景由 Prop asset generation 的纯色隔离背景合同负责" in prompt


def test_gold_thread_and_loom_use_one_canonical_instance_not_current_quantity():
    prompt = _prompt()
    gold_rule = next(line for line in prompt.splitlines() if line.startswith("- 上等金丝："))
    loom_rule = next(line for line in prompt.splitlines() if line.startswith("- 脚踏织机："))

    assert "一个标准线卷/一卷金丝" in gold_rule
    assert "不得因原文“一卷卷”而生成多个实例" in gold_rule
    assert "appearance 描述一架织机本体" in loom_rule
    for current_state in ("两架", "并排", "当前为空", "没有布匹正在成形"):
        assert current_state in loom_rule
    assert "当前剧情数量" in prompt


def test_clothing_and_wearable_assets_are_complete_single_objects():
    prompt = _prompt()
    clothing_rule = next(line for line in prompt.splitlines() if line.startswith("- 服装/可穿戴物"))
    blue_dress_rule = next(line for line in prompt.splitlines() if line.startswith("- 蓝色礼服："))

    for prop in ("蓝色礼服", "紫色长袍", "官服", "礼帽", "腰带"):
        assert prop in clothing_rule
    assert "一件/一顶/一条物件本身" in clothing_rule
    assert "不得要求多件、多套、前后多视图拼版、衣柜展示或当前有人穿着的完整人物场景" in clothing_rule
    assert "一件完整礼服的标准资产" in blue_dress_rule
    assert "不得生成多件、多套、多视图或人物穿着场景" in blue_dress_rule


def test_natural_sets_are_one_semantic_instance_not_one_physical_component():
    prompt = _prompt()
    natural_set_rule = next(line for line in prompt.splitlines() if line.startswith("- 天然集合例外："))

    for natural_set in ("一双靴子", "一副眼镜", "一套茶具", "一串钥匙", "一副手套"):
        assert natural_set in natural_set_rule
    assert "多个组成部分共同构成一个正常、完整的语义物件" in natural_set_rule
    assert "ONE CANONICAL SEMANTIC INSTANCE" in natural_set_rule
    assert "不是机械的 EXACTLY ONE PHYSICAL COMPONENT" in natural_set_rule


def test_current_story_state_exclusion_preserves_inherent_structure():
    prompt = _prompt()

    assert "CURRENT STORY STATE" in prompt
    assert "不是禁止物件自身的 STRUCTURAL STATE" in prompt
    for structure in ("箱盖", "折叠屏风的多扇结构", "剪刀的两片刀刃"):
        assert structure in prompt
    assert "keyword blacklist" not in prompt


def test_prop_parse_seed_and_runtime_fallback_share_one_file_authority():
    prompt = _prompt()

    assert SYSTEM_PROP_PARSE_TEMPLATES[0]["template"] == prompt
    assert SYSTEM_PROP_PARSE_TEMPLATES[0]["type"] == "prop_parse"
    assert "ONE CANONICAL SEMANTIC INSTANCE" in prompt
    assert '"existence": "REAL"' in prompt


def test_system_seed_sync_updates_standard_in_place_and_preserves_novel_override(db_session):
    standard = PromptTemplate(
        id=STANDARD_TEMPLATE_ID,
        name="标准道具解析",
        type="prop_parse",
        template="stale prop identity contract",
        is_system=True,
        is_active=True,
    )
    custom = PromptTemplate(
        name="小说自定义道具解析",
        type="prop_parse",
        template="novel-owned prop prompt",
        is_system=False,
        is_active=True,
    )
    db_session.add_all([standard, custom])
    db_session.flush()
    default_novel = Novel(title="standard prop prompt")
    override_novel = Novel(title="custom prop prompt", prop_parse_prompt_template_id=custom.id)
    db_session.add_all([default_novel, override_novel])
    db_session.commit()

    PromptTemplateService(db_session).init_system_templates()
    service = NovelService.__new__(NovelService)
    service.db = db_session
    resolved = service._resolve_parse_template(default_novel.id, "prop_parse")
    override = service._resolve_parse_template(override_novel.id, "prop_parse")

    assert resolved.id == STANDARD_TEMPLATE_ID
    assert resolved.template == _prompt()
    assert override.id == custom.id
    assert override.template == "novel-owned prop prompt"
    db_session.refresh(override_novel)
    assert override_novel.prop_parse_prompt_template_id == custom.id
    assert db_session.query(PromptTemplate).filter_by(type="prop_parse", is_system=True).count() == 1
