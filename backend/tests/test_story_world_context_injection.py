import json

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.novel import Novel
from app.services import story_world_context
from app.services.story_world_context import (
    StoryWorldContextRequiredError,
    ensure_story_world_context_rules,
    inject_locked_story_world_context,
)


CONTEXT = {
    "world_type": "童话",
    "era": "架空时代",
    "historical_period": "未明确的前现代时期",
    "geographic_scope": "欧洲文化语境的虚构王国",
    "cultural_system": "欧洲童话式宫廷与民间文化体系",
    "technology_level": "前工业时代",
    "allow_time_travel": False,
    "material_culture": {
        "clothing": "欧洲童话式前现代宫廷与民间服饰体系",
        "architecture": "欧洲童话式前现代宫廷与城镇建筑体系",
        "objects": "欧洲前现代宫廷与民间物质文化体系",
    },
    "visual_exclusions": ["东亚古代官服与传统建筑", "现代工业与数字设备"],
}


def test_asset_parse_requires_locked_story_world_context(db_engine, monkeypatch):
    testing_session = sessionmaker(bind=db_engine)
    monkeypatch.setattr(story_world_context, "SessionLocal", testing_session)
    with testing_session() as db:
        novel = Novel(title="未锁定小说")
        db.add(novel)
        db.commit()
        novel_id = novel.id

    with pytest.raises(StoryWorldContextRequiredError, match="请先确认并锁定"):
        inject_locked_story_world_context(novel_id, "parse_characters", "正文")


@pytest.mark.asyncio
async def test_gate_blocks_before_llm_client_is_called(db_engine, monkeypatch):
    from app.services.llm_service import LLMService

    testing_session = sessionmaker(bind=db_engine)
    monkeypatch.setattr(story_world_context, "SessionLocal", testing_session)
    with testing_session() as db:
        novel = Novel(title="未锁定小说")
        db.add(novel)
        db.commit()
        novel_id = novel.id

    called = False

    class FakeClient:
        async def chat_completion(self, **_kwargs):
            nonlocal called
            called = True
            return {"success": True, "content": "{}"}

    service = LLMService.__new__(LLMService)
    service.model = "test-model"
    service.max_tokens = None
    service.temperature = None
    monkeypatch.setattr(service, "_get_client", lambda: FakeClient())

    with pytest.raises(StoryWorldContextRequiredError):
        await service.chat_completion(
            "system",
            "正文",
            task_type="parse_scenes",
            novel_id=novel_id,
        )
    assert called is False


@pytest.mark.parametrize("task_type", ["parse_characters", "parse_scenes", "parse_props"])
def test_locked_context_is_injected_before_novel_text(db_engine, monkeypatch, task_type):
    testing_session = sessionmaker(bind=db_engine)
    monkeypatch.setattr(story_world_context, "SessionLocal", testing_session)
    with testing_session() as db:
        novel = Novel(
            title="皇帝的新装",
            story_world_context=json.dumps(CONTEXT, ensure_ascii=False),
            story_world_context_locked=True,
        )
        db.add(novel)
        db.commit()
        novel_id = novel.id

    content = inject_locked_story_world_context(novel_id, task_type, "原始小说正文")

    assert content.startswith("【STORY_WORLD_CONTEXT】")
    assert "地域范围：欧洲文化语境的虚构王国" in content
    assert "- 服饰：欧洲童话式前现代宫廷与民间服饰体系" in content
    assert "允许穿越：否" in content
    assert content.endswith("【NOVEL_TEXT】\n原始小说正文")


def test_custom_parse_prompt_receives_shared_world_context_rules():
    custom_prompt = "请解析并输出 JSON。"
    result = ensure_story_world_context_rules(custom_prompt, "parse_props")

    assert "Book 级世界约束" in result
    assert "material_culture.objects" in result
    assert ensure_story_world_context_rules(result, "parse_props") == result


def test_default_asset_parse_prompts_contain_domain_rules():
    from pathlib import Path

    prompt_dir = Path(__file__).parent.parent / "prompt_templates"
    character = (prompt_dir / "character_parse.txt").read_text(encoding="utf-8")
    scene = (prompt_dir / "scene_parse.txt").read_text(encoding="utf-8")
    prop = (prompt_dir / "prop_parse.txt").read_text(encoding="utf-8")

    assert "可在 STORY_WORLD_CONTEXT 约束范围内进行合理视觉补全" in character
    assert "material_culture.clothing" in character
    assert "material_culture.architecture" in scene
    assert "现代灯具" not in scene
    assert "【示例输出】" not in scene
    assert "不得使用可能产生跨时代理解的模糊名称" in scene
    assert "material_culture.objects" in prop
    assert "FICTIONAL_OR_NONEXISTENT" in prop
    assert "被提及不等于实际存在" in prop
