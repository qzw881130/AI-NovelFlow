"""Novel prompt selections use isolated DB data and never start generation."""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.constants.prompt_template import NOVEL_PROMPT_TEMPLATE_FIELDS, PROMPT_TEMPLATE_TYPES
from app.models.novel import Chapter, Novel, Character
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.models.task import Task
from app.repositories.novel_repository import NovelRepository
from app.services.novel_prompt_templates import resolve_novel_prompt_template
from app.services.shot_keyframe_service import ShotKeyframeService
from app.services.llm_service import LLMService


def _custom(db, template_type, name=None):
    template = PromptTemplate(name=name or template_type, type=template_type,
                              template=f"custom {template_type}", is_system=False, is_active=True)
    db.add(template)
    db.flush()
    return template


def test_registry_is_complete_for_novel_selection():
    chapter_music_types = {
        "background_music_director", "background_music_director_full", "background_music_generation",
    }
    retired_types = {"h3_multi_keyframe_prompt", "h3_execution_optimizer_prompt", "h3_preflight_repair_prompt"}
    chapter_scoped = chapter_music_types | {"subtitle_correction", "subtitle_translation"}
    assert set(NOVEL_PROMPT_TEMPLATE_FIELDS) - retired_types == set(PROMPT_TEMPLATE_TYPES) - chapter_scoped
    assert len(NOVEL_PROMPT_TEMPLATE_FIELDS) == 27
    assert len(set(NOVEL_PROMPT_TEMPLATE_FIELDS.values())) == 27
    assert all(hasattr(Novel, field) for field in NOVEL_PROMPT_TEMPLATE_FIELDS.values())


def test_create_edit_and_old_novel_default(client, db_session):
    task_count = db_session.query(Task).count()
    custom_09a = _custom(db_session, "temporal_reference_selector")
    custom_15 = _custom(db_session, "image_quality_review_prompt")
    custom_14a = _custom(db_session, "h3_preflight_repair_prompt")
    db_session.commit()

    default_response = client.post("/api/novels/", json={"title": "全部默认"})
    assert default_response.status_code == 200
    default_novel = db_session.get(Novel, default_response.json()["data"]["id"])
    for template_type, field in NOVEL_PROMPT_TEMPLATE_FIELDS.items():
        selected_id = getattr(default_novel, field)
        if template_type in {"character", "style"}:
            assert selected_id == resolve_novel_prompt_template(db_session, default_novel, template_type).id
        else:
            assert selected_id is None
            resolved = resolve_novel_prompt_template(db_session, default_novel, template_type)
            if template_type in {"h3_multi_keyframe_prompt", "h3_execution_optimizer_prompt", "h3_preflight_repair_prompt"}:
                assert resolved is None
            else:
                assert resolved.is_system
    assert default_novel.temporal_reference_selector_prompt_template_id is None
    assert default_novel.image_quality_review_prompt_template_id is None
    assert resolve_novel_prompt_template(db_session, default_novel, "temporal_reference_selector").is_system

    response = client.post("/api/novels/", json={
        "title": "自定义", "temporalReferenceSelectorPromptTemplateId": custom_09a.id,
        "imageQualityReviewPromptTemplateId": custom_15.id,
        "h3PreflightRepairPromptTemplateId": custom_14a.id,
    })
    assert response.status_code == 200
    novel_id = response.json()["data"]["id"]
    assert response.json()["data"]["temporalReferenceSelectorPromptTemplateId"] == custom_09a.id
    assert db_session.get(Novel, novel_id).image_quality_review_prompt_template_id == custom_15.id

    changed = client.put(f"/api/novels/{novel_id}", json={"imageQualityReviewPromptTemplateId": None})
    assert changed.status_code == 200
    db_session.expire_all()
    novel = db_session.get(Novel, novel_id)
    assert novel.image_quality_review_prompt_template_id is None
    assert novel.temporal_reference_selector_prompt_template_id == custom_09a.id
    assert novel.h3_preflight_repair_prompt_template_id == custom_14a.id
    assert db_session.query(Task).count() == task_count


def test_copy_inherits_valid_references_and_only_source_chapters(client, db_session):
    task_count = db_session.query(Task).count()
    chosen_types = ("temporal_reference_selector", "image_quality_review_prompt",
                    "h3_execution_optimizer_prompt", "h3_preflight_repair_prompt",
                    "clip_execution_planner")
    versions = {typ: _custom(db_session, typ) for typ in chosen_types}
    db_session.commit()
    source = Novel(title="来源", author="作者", description="简介", aspect_ratio="9:16",
                   **{NOVEL_PROMPT_TEMPLATE_FIELDS[typ]: version.id for typ, version in versions.items()})
    db_session.add(source)
    db_session.flush()
    db_session.add_all([
        Chapter(novel_id=source.id, number=2, title="第二章", content="正文二", parsed_data="{}", final_video="/video.mp4"),
        Chapter(novel_id=source.id, number=1, title="第一章", content="正文一", shot_images='["/image.png"]'),
        Character(novel_id=source.id, name="角色", image_url="/character.png"),
    ])
    db_session.commit()
    response = client.post(f"/api/novels/{source.id}/copy", json={"title": "副本"})
    assert response.status_code == 200
    copied = db_session.get(Novel, response.json()["data"]["id"])
    assert (copied.author, copied.description, copied.aspect_ratio) == ("作者", "简介", "9:16")
    for typ, version in versions.items():
        assert getattr(copied, NOVEL_PROMPT_TEMPLATE_FIELDS[typ]) == version.id
        assert resolve_novel_prompt_template(db_session, copied, typ).id == version.id
    chapters = db_session.query(Chapter).filter_by(novel_id=copied.id).order_by(Chapter.number).all()
    assert [(c.number, c.title, c.content) for c in chapters] == [(1, "第一章", "正文一"), (2, "第二章", "正文二")]
    assert all(c.parsed_data is None and c.shot_images is None and c.final_video is None for c in chapters)
    assert db_session.query(Character).filter_by(novel_id=copied.id).count() == 0
    assert db_session.query(Task).count() == task_count
    assert source.title == "来源" and source.temporal_reference_selector_prompt_template_id == versions["temporal_reference_selector"].id

    versions["h3_preflight_repair_prompt"].is_active = False
    db_session.commit()
    stale = client.post(f"/api/novels/{source.id}/copy", json={"title": "失效版本副本"})
    stale_copy = db_session.get(Novel, stale.json()["data"]["id"])
    assert stale_copy.h3_preflight_repair_prompt_template_id is None
    assert resolve_novel_prompt_template(db_session, stale_copy, "h3_preflight_repair_prompt") is None
    assert source.h3_preflight_repair_prompt_template_id == versions["h3_preflight_repair_prompt"].id


def test_copy_default_and_deleted_or_wrong_type_fallback(db_session):
    source = Novel(title="默认", temporal_reference_selector_prompt_template_id="deleted-id")
    db_session.add(source)
    db_session.commit()
    copied = NovelRepository(db_session).copy_with_chapters(source, "默认副本")
    assert copied.temporal_reference_selector_prompt_template_id is None
    assert source.temporal_reference_selector_prompt_template_id == "deleted-id"


def test_09a_actual_call_uses_selected_version_and_novel_id(db_session):
    system = PromptTemplate(name="系统 #09A", type="temporal_reference_selector",
                            template="system selector", is_system=True, is_active=True)
    custom = _custom(db_session, "temporal_reference_selector")
    novel = Novel(title="入口测试", temporal_reference_selector_prompt_template_id=custom.id)
    db_session.add_all([system, novel])
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="章")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1)
    db_session.add(shot)
    db_session.commit()
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return {"success": True, "content": '{"selected_references": []}'}

    service = ShotKeyframeService()
    service.llm_service = SimpleNamespace(chat_completion=complete)
    asyncio.run(service._select_references(db_session, novel, shot, {"frame_index": 1}, []))
    assert calls[-1]["system_prompt"] == custom.template
    assert calls[-1]["novel_id"] == novel.id
    novel.temporal_reference_selector_prompt_template_id = None
    asyncio.run(service._select_references(db_session, novel, shot, {"frame_index": 1}, []))
    assert calls[-1]["system_prompt"] == system.template


def test_asset_description_calls_resolve_novel_versions(db_session, monkeypatch):
    import app.core.database as database

    scene_version = _custom(db_session, "scene_setting")
    prop_version = _custom(db_session, "prop_appearance")
    novel = Novel(title="素材描述", scene_setting_prompt_template_id=scene_version.id,
                  prop_appearance_prompt_template_id=prop_version.id)
    db_session.add(novel)
    db_session.commit()
    monkeypatch.setattr(database, "SessionLocal", lambda: nullcontext(db_session))
    llm = object.__new__(LLMService)
    llm.chat_completion = AsyncMock(return_value={"success": True, "content": "ok"})
    asyncio.run(llm.generate_scene_setting("场景", "描述", novel_id=novel.id))
    assert llm.chat_completion.call_args.kwargs["system_prompt"] == scene_version.template
    assert llm.chat_completion.call_args.kwargs["novel_id"] == novel.id
    asyncio.run(llm.generate_prop_appearance("道具", "描述", novel_id=novel.id))
    assert llm.chat_completion.call_args.kwargs["system_prompt"] == prop_version.template
    assert llm.chat_completion.call_args.kwargs["novel_id"] == novel.id
