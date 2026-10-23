"""Character Prompt contract tests, not an LLM/NLP output validator."""
from pathlib import Path

import pytest

from app.constants.llm import DEFAULT_PARSE_CHARACTERS_PROMPT
from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.services.novel_service import NovelService
from app.services.prompt_template_service import (
    PromptTemplateService,
    SYSTEM_CHARACTER_PARSE_TEMPLATES,
)


PROMPT_FILE = Path(__file__).resolve().parents[1] / "prompt_templates" / "character_parse.txt"
STANDARD_TEMPLATE_ID = "14f1306c-722b-44f4-b3e8-6603aae22f44"


@pytest.fixture(params=["standard", "fallback"])
def prompt(request):
    if request.param == "standard":
        return PROMPT_FILE.read_text(encoding="utf-8")
    return DEFAULT_PARSE_CHARACTERS_PROMPT


@pytest.mark.parametrize("example,description_rule,appearance_rule", [
    (
        "原文“侍从双手捧着腰带”",
        "description 可以说明其在相关剧情中负责递送/捧持衣装",
        "appearance 不得写“固定双手托着腰带”“腰带是固定身份标记”，也不得要求固定捧持动作",
    ),
    (
        "原文“侍从举着巨大镜子”",
        "description 可以写“皇帝更衣室中的侍从之一，曾在皇帝试衣时负责举镜”",
        "appearance 不得写“固定双手举着巨大镜子”“镜框是固定身份标记”",
    ),
])
def test_current_prop_examples_keep_description_but_not_fixed_appearance(
    prompt, example, description_rule, appearance_rule
):
    rule = next(line for line in prompt.splitlines() if line.startswith(f"- {example}："))
    assert description_rule in rule
    assert appearance_rule in rule


def test_supported_stable_accessories_and_personal_equipment_remain_allowed(prompt):
    assert "原文明示“他常年佩戴一副圆框眼镜”：圆框眼镜有稳定身份依据，允许作为稳定 appearance" in prompt
    assert "固定眼镜、长期佩戴的首饰、徽章、明确稳定的头饰、有充分故事依据的个人装备及基础服装组成仍可进入 appearance" in prompt
    assert "原文明示的稳定配饰必须保留" in prompt
    assert "临时剧情交互物不因当前持有而成为身份配饰" in prompt


def test_numbered_characters_use_stable_not_current_state_differences(prompt):
    group_rules = prompt.split("【群体称谓抽取规则", 1)[1].split("【appearance", 1)[0]
    assert "脸型/五官/年龄/发型/发色/胡须/肤色/身高/体型/基础服装款式与配色/有依据的稳定佩饰/稳定身份标记" in group_rules
    assert "不得使用当前站位、动作、手持剧情物、表情或剧情姿态作为永久 Character identity 的主要区分方式" in group_rules
    assert "在不违反 STORY_WORLD_CONTEXT 的前提下进行稳定视觉补全" in group_rules
    assert "年龄/体型/服饰配色/站位/表情/动作/配饰等" not in group_rules
    assert "侍从1、侍从2" in group_rules
    assert "不得改名、合并或替换" in group_rules


def test_profession_alone_does_not_make_tools_permanent_identity(prompt):
    assert "职业本身不能自动证明职业工具属于永久 identity marker" in prompt
    assert "不能仅因“园丁”推导“固定在腰后的铲子”" in prompt
    assert "不能仅因“大臣”推导“左手永远拿着文件夹”" in prompt


def test_description_and_reference_display_are_separate_from_shot_state(prompt):
    assert "description 描述人物是谁、职业/社会身份、社会关系、背景、性格及剧情中的职责/经历" in prompt
    assert "允许保留有情境限定的事件叙述，不等于永久视觉身份" in prompt
    assert "当前手持/捧/举/递/拿的剧情交互物、当前动作、姿势、站位、朝向、视线、剧情表情或与其他角色/道具的互动关系" in prompt
    assert "允许中性站姿、自然姿态及中性/自然表情作为 Character Reference 展示方式" in prompt
    assert "它们不是当前 Shot 的固定动作合同" in prompt
    assert "Shot-specific clothing 强制设为不可变身份" in prompt
    assert "不得把当前剧情表情或嘴部动作锁定为永久身份" in prompt
    assert "只包含 1 个主体" in prompt
    assert "全身照/全身构图" in prompt
    assert "纯字符串的一段话" in prompt
    assert '"voice_prompt": "..."' in prompt


def test_standard_seed_and_fallback_share_the_same_character_authority_rules():
    seed = PROMPT_FILE.read_text(encoding="utf-8")
    assert SYSTEM_CHARACTER_PARSE_TEMPLATES[0]["template"] == seed
    # Compare only the shared contract, not the pre-existing world-context prose.
    for start, end in (
        ("【Character 稳定外观 authority boundary", "【角色命名唯一性与一致性"),
        ("【群体称谓抽取规则", "【appearance"),
    ):
        assert seed.split(start, 1)[1].split(end, 1)[0] == DEFAULT_PARSE_CHARACTERS_PROMPT.split(start, 1)[1].split(end, 1)[0]


def test_existing_seed_sync_updates_standard_in_place_and_keeps_novel_override(db_session):
    standard = PromptTemplate(
        id=STANDARD_TEMPLATE_ID,
        name="标准角色解析",
        type="character_parse",
        template="stale character appearance contract",
        is_system=True,
        is_active=True,
    )
    custom = PromptTemplate(
        name="小说自定义角色解析",
        type="character_parse",
        template="novel-owned custom prompt",
        is_system=False,
        is_active=True,
    )
    db_session.add_all([standard, custom])
    db_session.flush()
    default_novel = Novel(title="standard character prompt")
    override_novel = Novel(title="custom character prompt", character_parse_prompt_template_id=custom.id)
    db_session.add_all([default_novel, override_novel])
    db_session.commit()

    PromptTemplateService(db_session).init_system_templates()
    # Resolve through the real product method without constructing network clients.
    service = NovelService.__new__(NovelService)
    service.db = db_session
    resolved = service._resolve_parse_template(default_novel.id, "character_parse")
    override = service._resolve_parse_template(override_novel.id, "character_parse")

    assert resolved.id == STANDARD_TEMPLATE_ID
    assert resolved.template == PROMPT_FILE.read_text(encoding="utf-8")
    assert override.id == custom.id
    assert override.template == "novel-owned custom prompt"
    db_session.refresh(override_novel)
    assert override_novel.character_parse_prompt_template_id == custom.id
    assert db_session.query(PromptTemplate).filter_by(type="character_parse", is_system=True).count() == 1
