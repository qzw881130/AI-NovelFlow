"""Phase1 contracts and publication safety; run with --noconftest, no app lifespan."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.prompt_template import PromptTemplate
from app.models.llm_log import LLMLog
from app.models.task import Task
from app.models.chapter_asset_parse import ChapterAssetParseRun as Run, ChapterAssetCandidate as Candidate
from app.services.chapter_asset_parse_service import ChapterAssetParseService, expire_run_for_task
from app.schemas.chapter_asset_parse import validate_output
from app.api.chapter_asset_parses import router

PROMPTS = Path(__file__).parents[1] / "prompt_templates"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for kind, filename in (("character_parse", "character_parse.txt"), ("scene_parse", "scene_parse.txt"), ("prop_parse", "prop_parse.txt")):
            db.add(PromptTemplate(name=kind, type=kind, is_system=True, is_active=True,
                                  template=(PROMPTS / filename).read_text()))
        db.commit()
        yield db
    engine.dispose()


@pytest.fixture
def chapter(db_session):
    novel = Novel(title="测试小说")
    chapter = Chapter(novel=novel, number=1, title="第一回", content="刘备到桃园。三只白羊在草坡吃草。各置全身铠甲。")
    novel.characters = [Character(name="刘备", description="已接受描述", appearance="已接受外观", image_url="/accepted.png"),
                        Character(name="应保留的旧角色", reference_audio_url="/accepted.flac")]
    novel.scenes = [Scene(name="桃园", setting="已接受场景")]
    novel.props = [Prop(name="木杖", appearance="已接受道具")]
    db_session.add(novel)
    db_session.commit()
    return chapter


def character(name="刘备"):
    return {"name": name, "entity_type": "INDIVIDUAL", "group_size_hint": 1,
            "description": "本章人物", "appearance": "全身站立的成年男子，布衣布鞋，五官体型稳定。",
            "voice_prompt": None, "chapter_presence": {"role": "MAJOR"},
            "source_evidence": [{"text": "刘备到桃园"}], "chapter_appearances": []}


class FakeLLM:
    provider, model, timeout, max_tokens, temperature = "test", "test-model", 10, 12345, "0.2"

    def __init__(self, db, outputs=None, on_call=None, log=True, fail=False):
        self.db, self.on_call, self.log, self.fail = db, on_call, log, fail
        self.outputs = outputs or {"characters": {"characters": [character()]}, "scenes": {"scenes": []}, "props": {"props": []}}
        self.calls = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        if self.on_call:
            result = self.on_call()
            if asyncio.iscoroutine(result):
                await result
        if self.fail:
            return {"success": False, "failure_kind": "SERVICE_ERROR", "error": "test failure"}
        output = self.outputs[kwargs["task_type"].removeprefix("parse_")]
        raw = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        log_id = str(uuid4())
        if self.log:
            self.db.add(LLMLog(id=log_id, provider=self.provider, model=self.model, status="success",
                              novel_id=kwargs["novel_id"], chapter_id=kwargs["chapter_id"],
                              system_prompt=kwargs["system_prompt"], user_prompt=kwargs["user_content"],
                              prompt_template_name=kwargs["prompt_template_name"], response=raw, task_type=kwargs["task_type"]))
            self.db.commit()
        return {"success": True, "content": raw, "llm_log_id": log_id if self.log else None}


def execute(db, chapter, llm=None, kinds=None):
    return asyncio.run(ChapterAssetParseService(db, llm or FakeLLM(db)).parse(chapter.novel_id, chapter.id, kinds))


def test_persist_candidates_and_empty_results_without_touching_global_assets(db_session, chapter):
    db = db_session
    before = {model.__tablename__: [tuple(getattr(row, col.key) for col in model.__table__.columns)
              for row in db.query(model).order_by(model.id)] for model in (Character, Scene, Prop)}
    llm = FakeLLM(db)
    result = execute(db, chapter, llm)
    assert result["success"] is True
    data = result["data"]
    assert data["candidateCount"] == 1 and data["publishedToBook"] is False
    assert data["candidates"][0]["chapter_appearances"] == []
    assert data["candidates"][0]["id"] != db.query(Character).filter_by(name="刘备").one().id
    assert [call["emptyConfirmed"] for call in data["calls"]] == [False, True, True]
    assert all(call["llmLogId"] and call["template"]["hash"] for call in data["calls"])
    assert all(call["requestTemplate"]["version"] == "chapter-asset-request-v1" and call["requestTemplate"]["hash"] for call in data["calls"])
    assert data["calls"][0]["template"]["text"] == (PROMPTS / "character_parse.txt").read_text()
    assert "V3.1.2" in llm.calls[0]["system_prompt"]
    assert "{章节范围说明}" not in llm.calls[0]["system_prompt"]
    assert chapter.content in llm.calls[0]["user_content"]
    assert data["calls"][0]["maxTokens"] == 12345
    assert db.get(Task, data["taskId"]).status == "completed"
    assert chapter.parsed_data is None
    after = {model.__tablename__: [tuple(getattr(row, col.key) for col in model.__table__.columns)
             for row in db.query(model).order_by(model.id)] for model in (Character, Scene, Prop)}
    assert before == after


@pytest.mark.parametrize("kind,payload", [("characters", {}), ("characters", {"characters": None}),
    ("characters", {"characters": [dict(name="旧格式角色", appearance="旧外观")]}),
    ("scenes", {"scenes": [{"name": "桃园", "description": "园林", "setting": "桃树"}]}),
    ("props", {"props": [{"name": "木杖", "description": "工具", "appearance": "木质"}]}),
    ("characters", '```json\n{"characters": []}\n```'),
    ("characters", '{"characters":[],"characters":[]}'),
    ("characters", '{"characters":[],"unknown":NaN}')])
def test_invalid_output_is_failed_not_empty_success(db_session, chapter, kind, payload):
    result = execute(db_session, chapter, FakeLLM(db_session, {kind: payload}), [kind])
    assert result["success"] is False
    assert result["data"]["status"] == "FAILED"
    assert result["data"]["issues"][0]["code"] == "INVALID_CANDIDATE_OUTPUT"
    assert db_session.query(Candidate).count() == 0
    assert result["data"]["calls"][0]["response"] is not None


@pytest.mark.parametrize("change", [
    {"group_size_hint": True}, {"group_size_hint": None}, {"entity_type": "GROUP", "group_size_hint": 1},
    {"chapter_presence": {"role": "OTHER"}}, {"appearance": "第一段\n第二段"},
    {"source_evidence": [{"text": "刘备", "start": 0}]}, {"chapter_appearances": None},
    {"chapter_appearances": [{"event_key": "appearance_1", "change_type": "inherit", "appearance_description": None,
                              "source_evidence": [{"text": "刘备"}]}]},
    {"chapter_appearances": [{"event_key": "appearance_1", "change_type": "new", "appearance_description": None,
                              "source_evidence": [{"text": "刘备"}]}]},
])
def test_character_contract_rejects_ambiguous_types_or_fabricated_offsets(change):
    with pytest.raises(ValueError):
        validate_output("characters", json.dumps({"characters": [{**character(), **change}]}))


def test_group_and_collective_changes_survive_persistence(db_session, chapter):
    members = [character(name) for name in ("刘备", "关羽", "张飞")]
    for item in members:
        item["chapter_appearances"] = [{"event_key": "appearance_1", "change_type": "new",
             "appearance_description": "换穿全身铠甲", "source_evidence": [{"text": "各置全身铠甲"}]}]
    group = {**character("白羊群"), "entity_type": "GROUP", "group_size_hint": 3,
             "source_evidence": [{"text": "三只白羊"}]}
    result = execute(db_session, chapter, FakeLLM(db_session, {"characters": {"characters": members + [group]}}), ["characters"])
    assert result["success"]
    saved = {item["name"]: item for item in result["data"]["candidates"]}
    assert saved["白羊群"]["group_size_hint"] == 3
    assert saved["白羊群"]["chapter_appearances"] == []
    assert all(saved[name]["chapter_appearances"][0]["event_key"] == "appearance_1" for name in ("刘备", "关羽", "张飞"))


def test_duplicate_names_and_duplicate_event_keys_rejected():
    with pytest.raises(ValueError):
        validate_output("characters", json.dumps({"characters": [character(), character()]}))
    item = character()
    change = {"event_key": "appearance_1", "change_type": "uncertain", "appearance_description": None,
              "source_evidence": [{"text": "整装待发"}]}
    item["chapter_appearances"] = [change, deepcopy(change)]
    with pytest.raises(ValueError):
        validate_output("characters", json.dumps({"characters": [item]}))


def test_ungrounded_evidence_is_review_not_ready(db_session, chapter):
    item = {**character(), "source_evidence": [{"text": "原文没有的句子"}]}
    result = execute(db_session, chapter, FakeLLM(db_session, {"characters": {"characters": [item]}}), ["characters"])
    assert not result["success"] and result["data"]["status"] == "NEEDS_REVIEW"
    assert result["data"]["candidates"][0]["validationStatus"] == "NEEDS_REVIEW"
    assert db_session.get(Task, result["data"]["taskId"]).status == "completed"  # execution succeeded, evidence did not pass


def test_explicit_reparse_uses_verified_failure_feedback_without_patching_old_evidence(db_session, chapter):
    from app.services.chapter_asset_parse_service import request_template_current, load_repair_template
    bad = {**character(), "source_evidence": [{"text": "刘备到桃园。”"}]}
    first = execute(db_session, chapter, FakeLLM(db_session, {"characters": {"characters": [bad]}}), ["characters"])["data"]
    llm = FakeLLM(db_session)
    second = execute(db_session, chapter, llm, ["characters"])["data"]
    assert second["phase1Ready"] and len(llm.calls) == 1
    repair = second["calls"][0]["repair"]
    assert repair["template"] == load_repair_template()
    assert repair["previous_rejected_attempt"]["run_id"] == first["id"]
    assert repair["previous_rejected_attempt"]["llm_log_id"] == first["calls"][0]["llmLogId"]
    assert repair["previous_rejected_attempt"]["response"] == first["calls"][0]["response"]
    assert 'EVIDENCE_NOT_IN_SOURCE' in llm.calls[0]["user_content"]
    assert chapter.content in llm.calls[0]["user_content"]
    assert request_template_current(db_session.get(Run, second["id"]))
    assert db_session.get(Run, first["id"]).status == 'NEEDS_REVIEW'
    assert db_session.query(Candidate).filter_by(run_id=first["id"]).one().payload == bad
    assert db_session.query(Character).filter_by(name='刘备').one().appearance == '已接受外观'


@pytest.mark.parametrize('change', ['source', 'source_snapshot', 'log', 'task', 'task_scope', 'newer_failure'])
def test_reparse_does_not_adopt_stale_unverified_or_superseded_failure(db_session, chapter, change):
    bad = {**character(), "source_evidence": [{"text": "不存在的证据"}]}
    first = execute(db_session, chapter, FakeLLM(db_session, {"characters": {"characters": [bad]}}), ["characters"])["data"]
    if change == 'source':
        chapter.content += '后来回家。'
    elif change == 'source_snapshot':
        db_session.get(Run, first['id']).source_content += '伪造的历史正文'
    elif change == 'log':
        db_session.get(LLMLog, first['calls'][0]['llmLogId']).response = '{}'
    elif change == 'task':
        db_session.get(Task, first['taskId']).status = 'cancelled'
    elif change == 'task_scope':
        db_session.get(Task, first['taskId']).novel_id = 'another-book'
    else:
        assert not execute(db_session, chapter, FakeLLM(db_session, fail=True), ['characters'])['success']
    db_session.commit()
    llm = FakeLLM(db_session)
    result = execute(db_session, chapter, llm, ['characters'])
    assert result['success']
    assert result['data']['calls'][0]['repair'] is None
    assert 'previous_rejected_attempt' not in llm.calls[0]['user_content']


def test_repair_template_edit_invalidates_only_runs_that_used_it(db_session, chapter, tmp_path, monkeypatch):
    from app.services import chapter_asset_parse_service as service
    ordinary = execute(db_session, chapter, kinds=['characters'])['data']
    bad = {**character(), "source_evidence": [{"text": "不存在的证据"}]}
    execute(db_session, chapter, FakeLLM(db_session, {"characters": {"characters": [bad]}}), ['characters'])
    repaired = execute(db_session, chapter, kinds=['characters'])['data']
    definition = json.loads(service.REPAIR_TEMPLATE_PATH.read_text())
    definition['system_suffix'] += '__REPAIR_EDIT__'
    path = tmp_path / 'chapter_asset_parse_repair.json'
    path.write_text(json.dumps(definition))
    monkeypatch.setattr(service, 'REPAIR_TEMPLATE_PATH', path)
    assert service.request_template_current(db_session.get(Run, ordinary['id']))
    assert not service.request_template_current(db_session.get(Run, repaired['id']))
    assert service.run_response(db_session, db_session.get(Run, repaired['id']))['effectiveStatus'] == 'PARSER_OUTDATED'


@pytest.mark.parametrize("field", ["base_prop", "event_pose"])
def test_temporary_state_in_appearance_requires_review(db_session, chapter, field):
    item = character()
    if field == "base_prop":
        item["appearance"] += "手持木杖。"
    else:
        item["chapter_appearances"] = [{"event_key": "appearance_1", "change_type": "new",
            "appearance_description": "穿上铠甲，躺在床上。", "source_evidence": [{"text": "各置全身铠甲"}]}]
    result = execute(db_session, chapter, FakeLLM(db_session, {"characters": {"characters": [item]}}), ["characters"])
    assert result["data"]["status"] == "NEEDS_REVIEW"
    assert not result["data"]["phase1Ready"]


def test_second_kind_failure_does_not_publish_first_kind(db_session, chapter):
    result = execute(db_session, chapter, FakeLLM(db_session, {"characters": {"characters": [character()]}, "scenes": {}}), ["characters", "scenes"])
    assert not result["success"] and db_session.query(Candidate).count() == 0
    assert len(result["data"]["calls"]) == 2


@pytest.mark.parametrize("options,code", [({"fail": True}, "LLM_REQUEST_FAILED"), ({"log": False}, "LLM_LOG_UNVERIFIED")])
def test_provider_or_logging_failure_blocks_publication(db_session, chapter, options, code):
    result = execute(db_session, chapter, FakeLLM(db_session, **options), ["characters"])
    assert result["data"]["issues"][0]["code"] == code
    assert not result["success"] and db_session.query(Candidate).count() == 0


@pytest.mark.parametrize("mutate", ["source", "cancel"])
def test_source_change_or_cancel_during_llm_cannot_publish(db_session, chapter, mutate):
    def change():
        if mutate == "source":
            chapter.content += "新增正文"
        else:
            db_session.query(Task).filter_by(type="chapter_asset_parse").update({"status": "cancelled"})
        db_session.commit()
    result = execute(db_session, chapter, FakeLLM(db_session, on_call=change), ["characters"])
    assert result["data"]["status"] == "FAILED" and db_session.query(Candidate).count() == 0
    assert result["data"]["issues"][0]["code"] == "SOURCE_OR_TASK_CHANGED"
    if mutate == "cancel":
        assert db_session.get(Task, result["data"]["taskId"]).status == "cancelled"


def test_concurrent_admission_unique_gate(db_session, chapter):
    async def concurrent():
        with pytest.raises(HTTPException) as exc:
            await ChapterAssetParseService(db_session, FakeLLM(db_session)).parse(chapter.novel_id, chapter.id, ["props"])
        assert exc.value.status_code == 409
    result = execute(db_session, chapter, FakeLLM(db_session, on_call=concurrent), ["characters"])
    assert result["success"] and db_session.query(Task).count() == 1


def test_candidate_insert_failure_rolls_back_publication(db_session, chapter):
    def reject(mapper, connection, target):
        raise RuntimeError("candidate storage failure")
    event.listen(Candidate, "before_insert", reject)
    try:
        result = execute(db_session, chapter, kinds=["characters"])
    finally:
        event.remove(Candidate, "before_insert", reject)
    assert result["data"]["status"] == "FAILED"
    assert db_session.query(Candidate).count() == 0


def test_history_readonly_staleness_and_cross_book_scope(db_session, chapter):
    first = execute(db_session, chapter, kinds=["characters"])["data"]
    second = execute(db_session, chapter, FakeLLM(db_session, {"characters": {}}), ["characters"])["data"]
    app = FastAPI()
    app.include_router(router, prefix="/api/novels")
    app.dependency_overrides[get_db] = lambda: db_session
    base = f"/api/novels/{chapter.novel_id}/chapters/{chapter.id}/asset-parses"
    with TestClient(app) as client:
        history = client.get(base).json()["data"]
        assert history[0]["id"] == second["id"] and history[0]["status"] == "FAILED"
        older = client.get(base + "/" + first["id"]).json()["data"]
        assert older["effectiveStatus"] == "SUPERSEDED" and not older["phase1Ready"]
        assert client.get(base.replace(chapter.novel_id, "other-book") + "/" + first["id"]).status_code == 404
        chapter.content += "更改正文"
        db_session.commit()
        response = client.get(base + "/" + first["id"]).json()["data"]
        assert response["effectiveStatus"] == "STALE" and not response["phase1Ready"]
        assert db_session.get(Run, first["id"]).status == "SUCCEEDED"
        assert client.post(base, json={"kinds": []}).status_code == 422


def test_wrong_configured_template_fails_without_fallback(db_session, chapter):
    wrong = PromptTemplate(type="character_parse", name="旧自定义模板", template="旧拆群规则", is_active=True)
    db_session.add(wrong)
    db_session.flush()
    chapter.novel.character_parse_prompt_template_id = wrong.id
    db_session.commit()
    llm = FakeLLM(db_session)
    result = execute(db_session, chapter, llm, ["characters"])
    assert result["data"]["issues"][0]["code"] == "PARSER_TEMPLATE_INCOMPATIBLE"
    assert llm.calls == []


def test_migration_idempotent_and_no_legacy_backfill(db_session, chapter):
    from migrations.add_chapter_asset_candidates import upgrade
    upgrade(db_session.get_bind())
    upgrade(db_session.get_bind())
    assert {"chapter_asset_parse_runs", "chapter_asset_candidates"} <= set(inspect(db_session.get_bind()).get_table_names())
    assert db_session.query(Run).count() == 0


def test_expired_run_is_failed_without_model_replay(db_session, chapter):
    result = execute(db_session, chapter, kinds=["characters"])["data"]
    run = db_session.get(Run, result["id"])
    task = db_session.get(Task, result["taskId"])
    run.status = "RUNNING"
    run.expires_at = datetime.utcnow() - timedelta(seconds=1)
    task.status = "running"
    db_session.commit()
    assert expire_run_for_task(db_session, task)
    assert db_session.get(Run, run.id).status == "FAILED"
    assert db_session.get(Task, task.id).status == "failed"


def test_request_text_comes_from_json_and_edits_invalidate_old_inputs(db_session, chapter, tmp_path, monkeypatch):
    from app.services import chapter_asset_parse_service as service
    first = execute(db_session, chapter, kinds=["characters"])["data"]
    definition = json.loads(service.REQUEST_TEMPLATE_PATH.read_text())
    definition["common_instructions"] += "__FILE_EDIT_MARKER__"
    path = tmp_path / "chapter_asset_parse_request.json"
    path.write_text(json.dumps(definition, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(service, "REQUEST_TEMPLATE_PATH", path)
    old = service.run_response(db_session, db_session.get(Run, first["id"]))
    assert old["effectiveStatus"] == "PARSER_OUTDATED" and not old["phase1Ready"]
    llm = FakeLLM(db_session)
    second = execute(db_session, chapter, llm, ["characters"])["data"]
    assert second["phase1Ready"]
    assert "__FILE_EDIT_MARKER__" in llm.calls[0]["user_content"]
    assert second["calls"][0]["requestTemplate"]["hash"] == service.digest(path.read_text())


def test_invalid_request_json_fails_without_code_prompt_fallback(db_session, chapter, tmp_path, monkeypatch):
    from app.services import chapter_asset_parse_service as service
    path = tmp_path / "broken.json"
    path.write_text("{}")
    monkeypatch.setattr(service, "REQUEST_TEMPLATE_PATH", path)
    llm = FakeLLM(db_session)
    result = execute(db_session, chapter, llm, ["characters"])
    assert result["data"]["status"] == "FAILED"
    assert result["data"]["issues"][0]["code"] == "REQUEST_TEMPLATE_INVALID"
    assert llm.calls == []
