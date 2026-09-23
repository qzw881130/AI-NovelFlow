"""Locked Story World Context policy for asset parsing calls."""
import json

from app.core.database import SessionLocal
from app.models.novel import Novel
from app.schemas.novel import StoryWorldContext


ASSET_PARSE_TASK_TYPES = {"parse_characters", "parse_scenes", "parse_props"}
LOCK_REQUIRED_MESSAGE = "请先确认并锁定故事世界上下文"
RULE_MARKER = "【故事世界上下文（必须严格遵守）】"

COMMON_RULES = """【故事世界上下文（必须严格遵守）】
输入中会提供已经由用户确认并锁定的 STORY_WORLD_CONTEXT。它是当前小说的 Book 级世界约束。
1. 不得重新判断、修改或覆盖其中已经锁定的时代、历史时期、地域、文化体系、技术水平和物质文化体系。
2. 小说原文明示事实优先；不得为了符合一般世界约束而删除或篡改原文明示的特殊设定。
3. 原文未明确、需要推断或视觉补全的信息必须符合 STORY_WORLD_CONTEXT。
4. material_culture 是方向约束而非穷举白名单；visual_exclusions 是典型反例而非完整黑名单。
5. allow_time_travel = false 时，不得自行引入无原文依据的跨时代元素。
6. allow_time_travel = true 时，只允许保留原文明示或明确支持的跨时代元素，不得自行扩展。"""

DOMAIN_RULES = {
    "parse_characters": "角色的外貌补全、服装、发式、冠帽、饰品和身份视觉表现，必须符合时代、地域、文化体系及 material_culture.clothing。",
    "parse_scenes": "场景的建筑、街道、室内空间、陈设、照明和环境视觉补全，必须符合时代、地域、文化体系、technology_level 及 material_culture.architecture。对照明、交通、机械设施、城市设施等时代敏感元素，不得使用可能产生跨时代理解的模糊名称；如需补全，必须明确为符合当前技术水平的具体形态，无法可靠确定时不主动补充。",
    "parse_props": "道具的形制、材质、工艺、用途和技术表现，必须符合时代、地域、文化体系、technology_level 及 material_culture.objects。",
}


class StoryWorldContextRequiredError(RuntimeError):
    pass


def get_locked_story_world_context(novel_id: str) -> StoryWorldContext:
    if not novel_id:
        raise StoryWorldContextRequiredError(LOCK_REQUIRED_MESSAGE)
    db = SessionLocal()
    try:
        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        if not novel or not novel.story_world_context_locked or not novel.story_world_context:
            raise StoryWorldContextRequiredError(LOCK_REQUIRED_MESSAGE)
        try:
            return StoryWorldContext.model_validate(json.loads(novel.story_world_context))
        except Exception as exc:
            raise StoryWorldContextRequiredError("已锁定的故事世界上下文格式无效，请重新确认并锁定") from exc
    finally:
        db.close()


def render_story_world_context_block(context: StoryWorldContext) -> str:
    travel = "是" if context.allow_time_travel else "否"
    exclusions = "\n".join(f"- {item}" for item in context.visual_exclusions)
    return "\n".join([
        "【STORY_WORLD_CONTEXT】",
        f"世界类型：{context.world_type}",
        f"时代层级：{context.era}",
        f"具体历史时期：{context.historical_period}",
        f"地域范围：{context.geographic_scope}",
        f"文化体系：{context.cultural_system}",
        f"技术水平：{context.technology_level}",
        f"允许穿越：{travel}",
        "物质文化体系：",
        f"- 服饰：{context.material_culture.clothing}",
        f"- 建筑：{context.material_culture.architecture}",
        f"- 器物：{context.material_culture.objects}",
        "典型视觉排除：",
        exclusions,
    ])


def inject_locked_story_world_context(novel_id: str, task_type: str, user_content: str) -> str:
    if task_type not in ASSET_PARSE_TASK_TYPES:
        return user_content
    context = get_locked_story_world_context(novel_id)
    return f"{render_story_world_context_block(context)}\n\n【NOVEL_TEXT】\n{user_content}"


def ensure_story_world_context_rules(system_prompt: str, task_type: str) -> str:
    if task_type not in ASSET_PARSE_TASK_TYPES or RULE_MARKER in (system_prompt or ""):
        return system_prompt
    return f"{system_prompt}\n\n{COMMON_RULES}\n{DOMAIN_RULES[task_type]}"
