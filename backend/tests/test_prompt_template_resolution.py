"""Offline coverage for runtime template selection; all rows live in SQLite memory."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import shots as shot_api
from app.api.characters import get_character_prompt
from app.constants.prompt_template import NOVEL_PROMPT_TEMPLATE_FIELDS
from app.models.novel import Chapter, Character, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.models.task import Task
from app.repositories import CharacterRepository, ChapterRepository, NovelRepository, ShotRepository
from app.repositories.prompt_template import PromptTemplateRepository
from app.schemas.shot import PlanVideoKeyframesRequest
from app.services.novel_prompt_templates import resolve_novel_prompt_template
from app.services.character_service import CharacterService


def template(db, kind, *, template_id=None, system=False, active=True, created_at=None):
    row = PromptTemplate(
        id=template_id, name=f"{kind}:{template_id or 'new'}", type=kind,
        template=f"body:{kind}:{template_id or 'new'}"
                 + (" {appearance}" if kind == "character" else ""), is_system=system,
        is_active=active, created_at=created_at,
    )
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize("kind,getter", [
    ("shot_image_prompt", shot_api._get_shot_image_prompt_template),
    ("keyframe_planner", shot_api._get_keyframe_planner_template),
    ("keyframe_transition", shot_api._get_keyframe_transition_template),
])
def test_main_flow_type_active_selection_and_fallback(db_session, kind, getter):
    repo = PromptTemplateRepository(db_session)
    system = template(db_session, kind, system=True)
    user = template(db_session, kind)
    wrong = template(db_session, "style")
    inactive = template(db_session, kind, active=False)
    novel = Novel(title=kind)
    field = NOVEL_PROMPT_TEMPLATE_FIELDS[kind]

    for selected_id, expected in (
        (user.id, user), (wrong.id, system), (inactive.id, system),
        ("missing-id", system), (None, system),
    ):
        setattr(novel, field, selected_id)
        assert getter(novel, repo).id == expected.id

    system.is_active = False
    db_session.flush()
    setattr(novel, field, wrong.id)
    with pytest.raises(HTTPException, match="未配置"):
        getter(novel, repo)


def test_system_default_skips_inactive_and_ties_break_by_id(db_session):
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    template(db_session, "character", template_id="00-disabled", system=True,
             active=False, created_at=moment)
    template(db_session, "character", template_id="z-system", system=True, created_at=moment)
    chosen = template(db_session, "character", template_id="a-system", system=True, created_at=moment)
    template(db_session, "style", template_id="other-type", system=True, created_at=moment)
    assert PromptTemplateRepository(db_session).get_default_system_template("character").id == chosen.id
    assert PromptTemplateRepository(db_session).get_default_system_template("absent") is None


def test_character_preview_uses_same_safe_choice_as_generation(db_session):
    system = template(db_session, "character", system=True)
    user = template(db_session, "character")
    wrong = template(db_session, "style", system=True)
    inactive = template(db_session, "character", active=False)
    novel = Novel(title="角色预览", prompt_template_id=user.id)
    db_session.add(novel)
    db_session.flush()
    character = Character(novel_id=novel.id, name="甲", appearance="红衣")
    db_session.add(character)
    db_session.flush()

    for selected_id, expected in (
        (user.id, user), (wrong.id, system), (inactive.id, system),
        ("deleted", system), (None, system),
    ):
        novel.prompt_template_id = selected_id
        preview = asyncio.run(get_character_prompt(
            character.id, db_session, NovelRepository(db_session),
            CharacterRepository(db_session), PromptTemplateRepository(db_session)))
        assert preview["data"]["templateId"] == expected.id
        assert preview["data"]["template"] == expected.template
        assert PromptTemplateRepository(db_session).resolve_for_type(
            novel.prompt_template_id, "character").id == expected.id
        assert "红衣" in preview["data"]["prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_choice", ["wrong_type", "inactive", "missing"])
async def test_character_worker_uses_active_character_template_without_comfyui(
        db_session, monkeypatch, invalid_choice):
    system = template(db_session, "character", system=True)
    wrong = template(db_session, "style")
    inactive = template(db_session, "character", active=False)
    choices = {"wrong_type": wrong.id, "inactive": inactive.id, "missing": "deleted"}
    novel = Novel(title="离线生成", prompt_template_id=choices[invalid_choice])
    db_session.add(novel)
    db_session.flush()
    character = Character(novel_id=novel.id, name="甲", appearance="红衣")
    db_session.add(character)
    db_session.flush()
    task = Task(type="character", name="离线生成", novel_id=novel.id,
                character_id=character.id, status="pending")
    db_session.add(task)
    db_session.commit()
    task_id = task.id
    character_id = character.id
    expected_prompt = system.template.replace("{appearance}", "红衣")
    monkeypatch.setattr("app.core.database.SessionLocal", lambda: db_session)

    class StopBeforeComfyUI(Exception):
        pass

    def stop_after_prompt(**_kwargs):
        raise StopBeforeComfyUI("offline boundary")

    generate = AsyncMock()
    service = object.__new__(CharacterService)
    service.comfyui_service = SimpleNamespace(
        builder=SimpleNamespace(build_character_workflow=stop_after_prompt),
        generate_character_image=generate)
    await service._generate_portrait_task(task_id, character_id, "甲", "红衣", "")
    assert db_session.get(Task, task_id).prompt_text == expected_prompt
    generate.assert_not_awaited()


@pytest.mark.parametrize("kind", [
    "h3_multi_keyframe_prompt",
    "h3_execution_optimizer_prompt", "h3_preflight_repair_prompt",
])
def test_h3_existing_valid_selection_behavior_is_preserved(db_session, kind):
    system = template(db_session, kind, system=True)
    user = template(db_session, kind)
    novel = Novel(title="H3")
    setattr(novel, NOVEL_PROMPT_TEMPLATE_FIELDS[kind], user.id)
    assert resolve_novel_prompt_template(db_session, novel, kind).id == user.id
    setattr(novel, NOVEL_PROMPT_TEMPLATE_FIELDS[kind], None)
    assert resolve_novel_prompt_template(db_session, novel, kind).id == system.id


@pytest.mark.asyncio
async def test_known_old_08_copy_is_blocked_before_llm_or_plan_write(db_session):
    legacy = template(db_session, "keyframe_planner",
                      template_id="81901831-8915-4b8b-857f-58579af30e4a")
    template(db_session, "keyframe_planner", system=True)
    novel = Novel(title="旧副本", keyframe_planner_prompt_template_id=legacy.id)
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="一")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, video_director_plan='{"existing": true}')
    db_session.add(shot)
    db_session.commit()
    llm = SimpleNamespace(chat_completion=AsyncMock())

    with pytest.raises(HTTPException) as error:
        await shot_api.plan_video_keyframes(
            novel.id, chapter.id, shot.id, PlanVideoKeyframesRequest(force=True),
            db_session, NovelRepository(db_session), ChapterRepository(db_session),
            ShotRepository(db_session), PromptTemplateRepository(db_session), llm)
    assert error.value.status_code == 409
    llm.chat_completion.assert_not_awaited()
    db_session.expire_all()
    assert db_session.get(Shot, shot.id).video_director_plan == '{"existing": true}'
    assert db_session.get(Novel, novel.id).keyframe_planner_prompt_template_id == legacy.id


@pytest.mark.asyncio
async def test_known_old_10_copy_is_blocked_before_llm(db_session):
    legacy = template(db_session, "keyframe_transition",
                      template_id="47d43de5-ff23-4df8-bf50-b44ea06bd18f")
    template(db_session, "keyframe_transition", system=True)
    novel = Novel(title="旧副本", keyframe_transition_prompt_template_id=legacy.id)
    llm = SimpleNamespace(chat_completion=AsyncMock())
    keyframes = [{"index": 1}, {"index": 2}]

    with pytest.raises(HTTPException) as error:
        await shot_api._plan_keyframe_transitions(
            db_session, novel, SimpleNamespace(), SimpleNamespace(), keyframes,
            PromptTemplateRepository(db_session), llm)
    assert error.value.status_code == 409
    llm.chat_completion.assert_not_awaited()
    assert novel.keyframe_transition_prompt_template_id == legacy.id


@pytest.mark.asyncio
async def test_canonical_planning_preflights_old_10_before_08_llm(db_session):
    legacy = template(db_session, "keyframe_transition",
                      template_id="47d43de5-ff23-4df8-bf50-b44ea06bd18f")
    template(db_session, "keyframe_planner", system=True)
    template(db_session, "keyframe_transition", system=True)
    novel = Novel(title="旧过渡副本", keyframe_transition_prompt_template_id=legacy.id)
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="一")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, video_director_plan='{"existing": true}')
    db_session.add(shot)
    db_session.commit()
    llm = SimpleNamespace(chat_completion=AsyncMock())

    with pytest.raises(HTTPException) as error:
        await shot_api.plan_video_keyframes(
            novel.id, chapter.id, shot.id, PlanVideoKeyframesRequest(force=True),
            db_session, NovelRepository(db_session), ChapterRepository(db_session),
            ShotRepository(db_session), PromptTemplateRepository(db_session), llm)
    assert error.value.status_code == 409
    llm.chat_completion.assert_not_awaited()
    db_session.expire_all()
    assert db_session.get(Shot, shot.id).video_director_plan == '{"existing": true}'
