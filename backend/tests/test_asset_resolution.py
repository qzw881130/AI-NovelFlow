"""Phase2 integration boundaries, isolated DB and logged fake LLM transport."""
import asyncio
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session

from app.core.database import Base, get_db
from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.task import Task
from app.models.llm_log import LLMLog
from app.models.asset_resolution import (CharacterIdentity, CharacterAlias, AssetResolutionRun as Run,
    AssetResolutionDecision as Decision, ChapterCharacterBinding as Binding, ChapterSceneBinding,
    ChapterPropBinding, ChapterCharacterAppearanceEvent as AppearanceEvent, AssetResolutionOmission as Omission,
    AssetResolutionLease)
from app.services.asset_identity import catalog, load_policy, seed_aliases, row_snapshot
from app.services.asset_resolution_service import AssetResolutionService, binding_state, resolution_response
from app.services.chapter_asset_parse_service import digest
from app.schemas.asset_resolution import ReviewAction
from app.services.chapter_asset_pipeline import parse_and_resolve
from app.api.asset_resolutions import router
from test_chapter_asset_parse import db_session, chapter, execute, FakeLLM, character


def identity(db, actor, entity_type="INDIVIDUAL", context=None):
    db.flush()
    db.add(CharacterIdentity(character_id=actor.id, novel_id=actor.novel_id, entity_type=entity_type,
        group_size_hint=1 if entity_type == "INDIVIDUAL" else None, context=context or {}, provenance={"origin": "TEST"}))
    seed_aliases(db, actor, load_policy(), {"origin": "TEST"})
    db.commit()
    return actor


def extract(db, chapter, payloads, kind="characters"):
    result = execute(db, chapter, FakeLLM(db, {kind: {kind: payloads}}), [kind])
    assert result["success"], result
    return result["data"]


def output(resolution="NEW", target=None, matches=None, canonical=None):
    return {"resolution": resolution, "matched_character_id": target["asset_id"] if resolution == "EXISTING" else None,
        "canonical_name": canonical or (target["canonical_name"] if target else "袁绍"), "confidence": 0.95,
        "match_type": "SEMANTIC_MATCH" if resolution == "EXISTING" else resolution,
        "needs_review": resolution == "AMBIGUOUS", "candidate_matches": [
            {"character_id": item["asset_id"], "canonical_name": item["canonical_name"], "confidence": 0.5}
            for item in matches or []], "reason": "test decision"}


class ResolverLLM:
    provider, model, timeout = "test", "test-resolver", 10

    def __init__(self, db, respond=None, during=None, failure=False):
        self.db, self.respond, self.during, self.failure = db, respond, during, failure
        self.calls = []

    async def chat_completion(self, **kwargs):
        data = json.loads(kwargs["user_content"])
        self.calls.append(data)
        if self.during:
            value = self.during()
            if asyncio.iscoroutine(value):
                await value
        if self.failure:
            return {"success": False, "error": "test transport failure"}
        candidate = data.get("candidate_character") or data["candidate_asset"]
        result = self.respond(data) if self.respond else output(canonical=candidate["name"])
        raw = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        log = LLMLog(id=str(uuid4()), provider=self.provider, model=self.model, status="success", task_type=kwargs["task_type"],
            novel_id=kwargs["novel_id"], chapter_id=kwargs["chapter_id"], system_prompt=kwargs["system_prompt"],
            user_prompt=kwargs["user_content"], response=raw)
        self.db.add(log)
        self.db.commit()
        return {"success": True, "content": raw, "llm_log_id": log.id}


def resolve(db, chapter, llm=None, kinds=None, force=False):
    return asyncio.run(AssetResolutionService(db, llm or ResolverLLM(db)).resolve(chapter.novel_id, chapter.id, kinds or ["characters"], force))


def evidenced_character(name, evidence, *, entity_type="INDIVIDUAL"):
    payload = character(name)
    payload.update(entity_type=entity_type, group_size_hint=1 if entity_type == "INDIVIDUAL" else None,
                   source_evidence=[{"text": evidence}])
    return payload


def binding_snapshot(row):
    return {column.key: deepcopy(getattr(row, column.key)) for column in row.__table__.columns}


def action(db, chapter, review, operation, **kwargs):
    return AssetResolutionService(db).review(chapter.novel_id, chapter.id, review["id"], ReviewAction(
        action=operation, expected_catalog_hash=catalog(db, chapter.novel_id)[1], **kwargs))


def test_exact_existing_no_update_no_llm_and_idempotent_binding(db_session, chapter):
    db = db_session
    actor = identity(db, db.query(Character).filter_by(name="刘备").one())
    actor.voice_prompt, actor.reference_audio_url = "已接受声音", "/accepted.flac"
    db.commit()
    before = row_snapshot(actor)
    extract(db, chapter, [character()])
    llm = ResolverLLM(db)
    first = resolve(db, chapter, llm)
    assert first["success"]
    decision = first["data"]["decisions"][0]
    assert (decision["resolution"], decision["matchType"], decision["llmUsed"], decision["assetId"]) == ("EXISTING", "EXACT_NAME", False, actor.id)
    binding_id = db.query(Binding).one().id
    second = resolve(db, chapter, llm)
    assert second["reused"] and second["data"]["id"] == first["data"]["id"]
    assert resolve(db, chapter, llm, force=True)["success"]
    assert db.query(Binding).one().id == binding_id
    assert llm.calls == []
    db.refresh(actor)
    assert row_snapshot(actor) == before


@pytest.mark.parametrize("canonical,alias", [("刘备","玄德"),("关羽","云长"),("张飞","翼德"),("曹操","孟德")])
def test_strong_alias_without_llm(db_session, chapter, canonical, alias):
    db = db_session
    actor = db.query(Character).filter_by(novel_id=chapter.novel_id, name=canonical).first()
    actor = actor or Character(novel_id=chapter.novel_id, name=canonical, appearance="已接受")
    db.add(actor)
    identity(db, actor)
    extract(db, chapter, [character(alias)])
    llm = ResolverLLM(db)
    result = resolve(db, chapter, llm)
    assert result["success"]
    item = result["data"]["decisions"][0]
    assert item["matchType"] == "STRONG_ALIAS" and item["assetId"] == actor.id and not item["llmUsed"]
    assert llm.calls == []
    assert not db.query(Character).filter_by(novel_id=chapter.novel_id, name=alias).first()


def test_new_and_linked_appearance_proposal_then_repeat(db_session, chapter):
    payload = character("袁绍")
    payload["chapter_appearances"] = [{"event_key":"appearance_1","change_type":"new","appearance_description":"全身铠甲",
                                     "source_evidence":[{"text":"各置全身铠甲"}]}]
    extract(db_session, chapter, [payload])
    result = resolve(db_session, chapter)
    assert result["success"]
    actor = db_session.query(Character).filter_by(name="袁绍").one()
    assert actor.entity_type == "INDIVIDUAL"
    event_row = db_session.query(AppearanceEvent).one()
    assert event_row.character_id == actor.id and event_row.source_start is None and event_row.status == "PENDING_LOCATION"
    repeat = resolve(db_session, chapter, force=True)
    assert repeat["success"] and repeat["data"]["decisions"][0]["matchType"] == "EXACT_NAME"
    assert db_session.query(Character).filter_by(name="袁绍").count() == 1
    assert db_session.query(AppearanceEvent).one().id == event_row.id


def groups(db, chapter):
    one = Character(novel_id=chapter.novel_id, name="村民", description="东村居民")
    two = Character(novel_id=chapter.novel_id, name="西村村民", description="西村居民")
    db.add_all([one,two])
    identity(db, one, "GROUP")
    identity(db, two, "GROUP")
    payload = {**character("村民"), "entity_type":"GROUP", "group_size_hint":None}
    extract(db, chapter, [payload])
    def ambiguous(data):
        matches = [item for item in data["existing_candidates"] if item["entity_type"] == "GROUP"]
        return output("AMBIGUOUS", matches=matches, canonical="村民")
    llm = ResolverLLM(db, ambiguous)
    result = resolve(db, chapter, llm)
    assert result["data"]["status"] == "NEEDS_REVIEW"
    assert llm.calls  # generic exact name must not skip semantic resolution
    assert db.query(Binding).count() == 0
    assert db.query(Character).filter_by(novel_id=chapter.novel_id).count() == 4
    return result["data"]["reviews"][0], one, two


@pytest.mark.parametrize("operation", ["MATCH","CREATE","IGNORE"])
def test_ambiguous_actions_only_publish_after_confirmation(db_session, chapter, operation):
    review, one, two = groups(db_session, chapter)
    before = row_snapshot(one)
    if operation == "CREATE":
        with pytest.raises(HTTPException) as exc:
            action(db_session, chapter, review, "CREATE", canonical_name="村民")
        assert exc.value.status_code == 422
        result = action(db_session, chapter, review, operation, canonical_name="安喜县衙外百姓")
        assert db_session.query(Character).filter_by(name="安喜县衙外百姓").one().entity_type == "GROUP"
    elif operation == "MATCH":
        result = action(db_session, chapter, review, operation, asset_id=one.id)
        assert db_session.query(Binding).one().character_id == one.id
    else:
        result = action(db_session, chapter, review, operation)
        assert db_session.query(Binding).count() == 0
    assert result["data"]["phase2Ready"] and result["data"]["reviews"] == []
    db_session.refresh(one)
    assert row_snapshot(one) == before
    with pytest.raises(HTTPException):
        action(db_session, chapter, review, "IGNORE")


def test_legacy_type_requires_explicit_sidecar_confirmation(db_session, chapter):
    actor = db_session.query(Character).filter_by(name="刘备").one()
    before = row_snapshot(actor)
    extract(db_session, chapter, [character()])
    result = resolve(db_session, chapter)
    review = result["data"]["reviews"][0]
    assert db_session.query(Binding).count() == 0
    with pytest.raises(HTTPException):
        action(db_session, chapter, review, "MATCH", asset_id=actor.id)
    result = action(db_session, chapter, review, "MATCH", asset_id=actor.id, confirm_legacy_type=True)
    assert result["data"]["phase2Ready"]
    db_session.refresh(actor)
    assert row_snapshot(actor) == before
    assert actor.entity_type == "INDIVIDUAL"


def test_contextual_group_alias_uses_llm_and_only_top_five(db_session, chapter):
    db = db_session
    group = Character(novel_id=chapter.novel_id, name="黄巾军", description="张宝统领的黄巾起义军")
    db.add(group)
    identity(db, group, "GROUP", {"faction":"黄巾军", "location":"山口"})
    for index in range(15):
        actor = Character(novel_id=chapter.novel_id, name=f"其他人物{index}")
        db.add(actor)
        identity(db, actor)
    payload = {**character("贼众"), "entity_type":"GROUP", "group_size_hint":None, "description":"张宝率领的队伍"}
    extract(db, chapter, [payload])
    def matched(data):
        target = next(item for item in data["existing_candidates"] if item["asset_id"] == group.id)
        return {**output("EXISTING", target), "match_type":"CONTEXTUAL_ALIAS"}
    llm = ResolverLLM(db, matched)
    result = resolve(db, chapter, llm)
    assert result["success"]
    assert len(llm.calls[0]["existing_candidates"]) == 5
    item = result["data"]["decisions"][0]
    assert item["matchType"] == "CONTEXTUAL_ALIAS" and item["llmUsed"] and item["assetId"] == group.id


@pytest.mark.parametrize("bad", ["foreign_id","wrong_name","type_conflict","invalid_schema","bad_json","transport"])
def test_resolver_failure_never_becomes_new(db_session, chapter, bad):
    actor = identity(db_session, db_session.query(Character).filter_by(name="刘备").one())
    payload = character("袁绍")
    if bad == "type_conflict":
        payload.update(entity_type="GROUP", group_size_hint=None)
    extract(db_session, chapter, [payload])
    def respond(data):
        target = next(item for item in data["existing_candidates"] if item["asset_id"] == actor.id)
        result = output("EXISTING", target)
        if bad == "foreign_id": result["matched_character_id"] = "outside-shortlist"
        if bad == "wrong_name": result["canonical_name"] = "not-the-saved-name"
        if bad == "invalid_schema": result["resolution"] = "NEW"
        if bad == "bad_json": return "not json"
        return result
    result = resolve(db_session, chapter, ResolverLLM(db_session, respond, failure=bad=="transport"))
    assert not result["success"] and result["data"]["status"] == "FAILED"
    assert db_session.query(Binding).count() == 0
    assert db_session.query(Character).filter_by(name="袁绍").count() == 0
    assert result["data"]["reviews"] == []


@pytest.mark.parametrize("what", ["source","catalog","cancel"])
def test_changes_during_llm_are_fenced(db_session, chapter, what):
    extract(db_session, chapter, [character("袁绍")])
    def change():
        if what == "source": chapter.content += "改变"
        elif what == "catalog": db_session.add(Character(novel_id=chapter.novel_id, name="并发新增"))
        else: db_session.query(Task).filter_by(type="chapter_asset_resolution").update({"status":"cancelled"})
        db_session.commit()
    result = resolve(db_session, chapter, ResolverLLM(db_session, during=change))
    assert result["data"]["status"] == "FAILED"
    assert not db_session.query(Character).filter_by(name="袁绍").first()
    assert db_session.query(Binding).count() == 0
    assert db_session.query(AssetResolutionLease).count() == 0


def test_stale_parse_and_failed_force_do_not_reuse_old_bindings(db_session, chapter):
    actor = identity(db_session, db_session.query(Character).filter_by(name="刘备").one())
    extract(db_session, chapter, [character()])
    assert resolve(db_session, chapter)["success"]
    extract(db_session, chapter, [character("袁绍")])
    assert binding_state(db_session, chapter.novel_id, chapter.id)["assets"]["characters"]["status"] == "STALE"
    failed = resolve(db_session, chapter, ResolverLLM(db_session, failure=True))
    assert failed["data"]["status"] == "FAILED"
    state = binding_state(db_session, chapter.novel_id, chapter.id)
    assert state["assets"]["characters"]["bindings"] == []
    assert db_session.get(Character, actor.id)


def test_same_source_shrinking_parse_carries_direct_parent_without_historical_union(db_session, chapter):
    db = db_session
    chapter.content = "刘备到桃园。关羽在园中等候。"
    liu = identity(db, db.query(Character).filter_by(name="刘备").one())
    guan = Character(novel_id=chapter.novel_id, name="关羽", description="关羽", appearance="关羽外观")
    db.add(guan); identity(db, guan)
    first_parse = extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"),
                                        evidenced_character("关羽", "关羽在园中等候")])
    first = resolve(db, chapter)
    assert first["success"]
    original = {row.character_id: row.id for row in db.query(Binding)}

    second_parse = extract(db, chapter, [evidenced_character("刘备", "刘备到桃园")])
    second = resolve(db, chapter)
    assert second["success"] and first_parse["sourceHash"] == second_parse["sourceHash"]
    omissions = db.query(Omission).filter_by(run_id=second["data"]["id"]).all()
    assert [(row.asset_id, row.status, row.reason_code) for row in omissions] == [
        (guan.id, "CARRIED", "IDENTICAL_SOURCE_AUTHORITATIVE_PARENT")]
    rows = {row.character_id: row for row in db.query(Binding)}
    assert set(rows) == {liu.id, guan.id}
    assert rows[liu.id].id == original[liu.id] and rows[liu.id].resolution_method == "EXACT_NAME"
    assert rows[guan.id].id == original[guan.id]
    assert rows[guan.id].resolution_method == "SOURCE_EVIDENCE_CARRY_FORWARD"
    assert rows[guan.id].resolution_run_id == second["data"]["id"]
    state = binding_state(db, chapter.novel_id, chapter.id)["assets"]["characters"]
    assert state["status"] == "SUCCEEDED" and not state["emptyConfirmed"]
    assert {row["assetId"] for row in state["bindings"]} == {liu.id, guan.id}
    assert all("membershipEvidence" not in row for row in state["bindings"])
    app=FastAPI();app.include_router(router,prefix="/api/novels");app.dependency_overrides[get_db]=lambda:db
    with TestClient(app) as client:
        projected=client.get(f"/api/novels/{chapter.novel_id}/chapters/{chapter.id}/asset-bindings").json()["data"]
    assert all(row["membershipEvidence"] == row["sourceEvidence"]
               for row in projected["assets"]["characters"]["bindings"])

    third_parse = extract(db, chapter, [evidenced_character("刘备", "刘备到桃园")])
    third = resolve(db, chapter)
    assert third["success"] and third_parse["sourceHash"] == second_parse["sourceHash"]
    assert db.query(Binding).filter_by(character_id=guan.id).one().id == original[guan.id]
    assert db.query(Omission).filter_by(run_id=third["data"]["id"], asset_id=guan.id, status="CARRIED").count() == 1


def test_alias_to_same_canonical_asset_is_applied_not_omitted(db_session, chapter):
    db = db_session
    actor = identity(db, db.query(Character).filter_by(name="刘备").one())
    extract(db, chapter, [character("刘备")]); assert resolve(db, chapter)["success"]
    binding_id = db.query(Binding).one().id
    extract(db, chapter, [character("玄德")])
    llm = ResolverLLM(db)
    result = resolve(db, chapter, llm)
    assert result["success"] and not llm.calls
    assert result["data"]["decisions"][0]["matchType"] == "STRONG_ALIAS"
    assert result["data"]["decisions"][0]["assetId"] == actor.id
    assert result["data"]["omissions"] == []
    row = db.query(Binding).one()
    assert row.id == binding_id and row.character_id == actor.id and row.resolution_method == "STRONG_ALIAS"


def test_changed_carry_proof_or_task_fails_binding_state_closed(db_session, chapter):
    db = db_session
    chapter.content = "刘备到桃园。关羽在园中等候。"
    identity(db, db.query(Character).filter_by(name="刘备").one())
    guan = Character(novel_id=chapter.novel_id, name="关羽", description="关羽", appearance="关羽外观")
    db.add(guan); identity(db, guan)
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"),
                          evidenced_character("关羽", "关羽在园中等候")])
    assert resolve(db, chapter)["success"]
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园")])
    carried = resolve(db, chapter)
    assert carried["success"]
    run = db.get(Run, carried["data"]["id"])
    omission = db.query(Omission).filter_by(run_id=run.id).one()
    original_proof, original_hash = deepcopy(omission.proof), omission.proof_hash
    omission.proof = {**omission.proof, "tampered": True}; db.commit()
    assert resolution_response(db, run)["effectiveStatus"] == "STALE"
    assert binding_state(db, chapter.novel_id, chapter.id)["assets"]["characters"]["status"] == "STALE"
    omission.proof, omission.proof_hash = original_proof, original_hash; db.commit()
    task = db.get(Task, run.task_id); task.status = "failed"; db.commit()
    assert binding_state(db, chapter.novel_id, chapter.id)["assets"]["characters"]["status"] == "STALE"
    task.status = "completed"
    guan.identity.entity_type = "GROUP"; guan.identity.group_size_hint = None; db.commit()
    assert binding_state(db, chapter.novel_id, chapter.id)["assets"]["characters"]["status"] == "STALE"
    guan.identity.entity_type = "INDIVIDUAL"; guan.identity.group_size_hint = 1; db.commit()
    db.delete(db.query(Binding).filter_by(character_id=guan.id).one()); db.commit()
    state = binding_state(db, chapter.novel_id, chapter.id)["assets"]["characters"]
    assert state["status"] == "STALE" and not state["emptyConfirmed"]


def test_tampered_carry_link_cannot_be_laundered_by_next_reparse(db_session, chapter):
    db = db_session
    chapter.content = "刘备到桃园。关羽在园中等候。"
    identity(db, db.query(Character).filter_by(name="刘备").one())
    guan = Character(novel_id=chapter.novel_id, name="关羽", description="关羽", appearance="关羽外观")
    db.add(guan); identity(db, guan)
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"),
                          evidenced_character("关羽", "关羽在园中等候")])
    assert resolve(db, chapter)["success"]
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园")])
    assert resolve(db, chapter)["success"]
    row = db.query(Binding).filter_by(character_id=guan.id).one()
    row.provenance = deepcopy(row.provenance)
    row.provenance[-1] = {**row.provenance[-1], "proof_hash":"tampered"}
    db.commit()
    assert binding_state(db, chapter.novel_id, chapter.id)["assets"]["characters"]["status"] == "STALE"
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园")])
    result = resolve(db, chapter)
    omission = db.query(Omission).filter_by(run_id=result["data"]["id"], asset_id=guan.id).one()
    assert not result["success"] and omission.status == "PENDING_REVIEW"
    assert omission.reason_code == "PARENT_PROVENANCE_INCOMPLETE"
    assert "PARENT_CARRY_BINDING_CHANGED" in omission.proof["parent_provenance_issues"]


def test_group_split_topology_conflict_is_pending_and_does_not_publish(db_session, chapter):
    db = db_session
    chapter.content = "黄巾军奉命分兵。东门部众守城。西门部众押粮。"
    group = Character(novel_id=chapter.novel_id, name="黄巾军", description="原黄巾军", appearance="黄巾军外观")
    db.add(group); identity(db, group, "GROUP")
    old = evidenced_character("黄巾军", "黄巾军奉命分兵", entity_type="GROUP")
    extract(db, chapter, [old]); assert resolve(db, chapter)["success"]
    parent = db.query(Binding).one()
    parent_snapshot = binding_snapshot(parent)
    split = [evidenced_character("东门黄巾军", "东门部众守城", entity_type="GROUP"),
             evidenced_character("西门黄巾军", "西门部众押粮", entity_type="GROUP")]
    extract(db, chapter, split)
    llm = ResolverLLM(db, lambda data: output("NEW", canonical=(data.get("candidate_character") or data["candidate_asset"])["name"]))
    result = resolve(db, chapter, llm)
    assert not result["success"] and result["data"]["status"] == "NEEDS_REVIEW"
    omission = db.query(Omission).filter_by(run_id=result["data"]["id"]).one()
    assert omission.asset_id == group.id and omission.status == "PENDING_REVIEW"
    assert omission.reason_code == "IDENTITY_TOPOLOGY_CONFLICT"
    assert {item["code"] for item in omission.proof["identity_conflicts"]} == {"GROUP_TOPOLOGY_CHANGED"}
    db.refresh(parent)
    assert binding_snapshot(parent) == parent_snapshot
    assert db.query(Binding).count() == 1


def test_incomplete_parent_provenance_is_pending_without_mutating_bindings(db_session, chapter):
    db = db_session
    chapter.content = "刘备到桃园。关羽在园中等候。"
    identity(db, db.query(Character).filter_by(name="刘备").one())
    guan = Character(novel_id=chapter.novel_id, name="关羽", description="关羽", appearance="关羽外观")
    db.add(guan); identity(db, guan)
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"),
                          evidenced_character("关羽", "关羽在园中等候")])
    assert resolve(db, chapter)["success"]
    parent_rows = {row.character_id: row for row in db.query(Binding)}
    parent_rows[guan.id].provenance = []
    db.commit()
    before = {key: binding_snapshot(row) for key, row in parent_rows.items()}
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园")])
    result = resolve(db, chapter)
    assert not result["success"] and result["data"]["status"] == "NEEDS_REVIEW"
    omission = db.query(Omission).filter_by(run_id=result["data"]["id"]).one()
    assert omission.status == "PENDING_REVIEW" and omission.reason_code == "PARENT_PROVENANCE_INCOMPLETE"
    assert "PARENT_BINDING_PROVENANCE_CHANGED" in omission.proof["parent_provenance_issues"]
    assert {row.character_id: binding_snapshot(row) for row in db.query(Binding)} == before


def test_changed_parent_resolver_log_prevents_carry(db_session, chapter):
    db = db_session
    chapter.content = "村民聚集。"
    group = Character(novel_id=chapter.novel_id, name="村民", description="本地村民", appearance="村民外观")
    db.add(group); identity(db, group, "GROUP")
    payload = evidenced_character("村民", "村民聚集", entity_type="GROUP")
    extract(db, chapter, [payload])
    def matched(data):
        target = next(item for item in data["existing_candidates"] if item["asset_id"] == group.id)
        return output("EXISTING", target)
    first = resolve(db, chapter, ResolverLLM(db, matched))
    assert first["success"]
    decision = db.query(Decision).filter_by(run_id=first["data"]["id"]).one()
    db.get(LLMLog, decision.call["llmLogId"]).response = "tampered"
    db.commit()
    extract(db, chapter, [])
    result = resolve(db, chapter)
    omission = db.query(Omission).filter_by(run_id=result["data"]["id"]).one()
    assert not result["success"] and omission.reason_code == "PARENT_PROVENANCE_INCOMPLETE"
    assert "PARENT_RESOLVER_LOG_CHANGED" in omission.proof["parent_provenance_issues"]


def test_changed_source_omission_is_pending_not_carried_or_deleted(db_session, chapter):
    db = db_session
    chapter.content = "刘备到桃园。关羽在园中等候。"
    identity(db, db.query(Character).filter_by(name="刘备").one())
    guan = Character(novel_id=chapter.novel_id, name="关羽", description="关羽", appearance="关羽外观")
    db.add(guan); identity(db, guan)
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"),
                          evidenced_character("关羽", "关羽在园中等候")])
    assert resolve(db, chapter)["success"]
    before = {row.character_id: binding_snapshot(row) for row in db.query(Binding)}
    chapter.content += "新增正文。"; db.commit()
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园")])
    result = resolve(db, chapter)
    omission = db.query(Omission).filter_by(run_id=result["data"]["id"]).one()
    assert not result["success"] and omission.status == "PENDING_REVIEW"
    assert omission.reason_code == "SOURCE_HASH_CHANGED" and not omission.proof["same_source"]
    assert {row.character_id: binding_snapshot(row) for row in db.query(Binding)} == before


def test_binding_baseline_change_during_planning_aborts_without_reconciliation(db_session, chapter):
    db = db_session
    chapter.content = "刘备到桃园。关羽在园中等候。袁绍随后到场。"
    identity(db, db.query(Character).filter_by(name="刘备").one())
    guan = Character(novel_id=chapter.novel_id, name="关羽", description="关羽", appearance="关羽外观")
    db.add(guan); identity(db, guan)
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"),
                          evidenced_character("关羽", "关羽在园中等候")])
    assert resolve(db, chapter)["success"]
    guan_binding = db.query(Binding).filter_by(character_id=guan.id).one()
    def mutate_parent():
        guan_binding.provenance = deepcopy(guan_binding.provenance) + [{"external_change": True}]
        db.commit()
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"),
                          evidenced_character("袁绍", "袁绍随后到场")])
    result = resolve(db, chapter, ResolverLLM(db, during=mutate_parent))
    assert not result["success"] and result["data"]["status"] == "FAILED"
    assert "BINDING_BASELINE_CHANGED" in result["data"]["issues"][0]["message"]
    assert db.query(Binding).filter_by(character_id=guan.id).one().provenance[-1] == {"external_change": True}
    assert not db.query(Character).filter_by(name="袁绍").first()
    assert db.query(Omission).filter_by(run_id=result["data"]["id"]).count() == 0


def test_same_source_character_with_parent_appearance_event_requires_review(db_session, chapter):
    db = db_session
    chapter.content = "刘备到桃园。关羽披甲。"
    identity(db, db.query(Character).filter_by(name="刘备").one())
    guan = Character(novel_id=chapter.novel_id, name="关羽", description="关羽", appearance="关羽外观")
    db.add(guan); identity(db, guan)
    guan_candidate = evidenced_character("关羽", "关羽披甲")
    guan_candidate["chapter_appearances"] = [{"event_key":"appearance_1", "change_type":"new",
        "appearance_description":"换穿全身铠甲", "source_evidence":[{"text":"关羽披甲"}]}]
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"), guan_candidate])
    assert resolve(db, chapter)["success"]
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"),
                          evidenced_character("关羽", "关羽披甲")])
    assert resolve(db, chapter)["success"]
    parent = db.query(Binding).filter_by(character_id=guan.id).one()
    parent_snapshot = binding_snapshot(parent)
    event_snapshot = row_snapshot(db.query(AppearanceEvent).filter_by(character_id=guan.id).one())
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园")])
    result = resolve(db, chapter)
    omission = db.query(Omission).filter_by(run_id=result["data"]["id"]).one()
    assert not result["success"] and omission.status == "PENDING_REVIEW"
    assert omission.reason_code == "APPEARANCE_EVENT_LINEAGE_UNSUPPORTED"
    db.refresh(parent)
    assert binding_snapshot(parent) == parent_snapshot
    assert row_snapshot(db.query(AppearanceEvent).filter_by(character_id=guan.id).one()) == event_snapshot


def test_missing_parent_appearance_event_invalidates_carry_provenance(db_session, chapter):
    db = db_session
    chapter.content = "刘备到桃园。关羽披甲。"
    identity(db, db.query(Character).filter_by(name="刘备").one())
    guan = Character(novel_id=chapter.novel_id, name="关羽", description="关羽", appearance="关羽外观")
    db.add(guan); identity(db, guan)
    payload = evidenced_character("关羽", "关羽披甲")
    payload["chapter_appearances"] = [{"event_key":"appearance_1", "change_type":"new",
        "appearance_description":"换穿全身铠甲", "source_evidence":[{"text":"关羽披甲"}]}]
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"), payload])
    assert resolve(db, chapter)["success"]
    db.delete(db.query(AppearanceEvent).filter_by(character_id=guan.id).one()); db.commit()
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园")])
    result = resolve(db, chapter)
    omission = db.query(Omission).filter_by(run_id=result["data"]["id"]).one()
    assert omission.status == "PENDING_REVIEW" and omission.reason_code == "PARENT_PROVENANCE_INCOMPLETE"
    assert "PARENT_APPEARANCE_EVENT_SET_CHANGED" in omission.proof["parent_provenance_issues"]


@pytest.mark.parametrize("kind,binding_model,payload", [
    ("scenes", ChapterSceneBinding, {"name":"桃园", "description":"桃园", "setting":"桃树",
        "source_evidence":[{"text":"刘备到桃园"}]}),
    ("props", ChapterPropBinding, {"name":"木杖", "description":"木杖", "appearance":"木质长杖",
        "source_evidence":[{"text":"木杖立在门边"}]}),
])
def test_same_source_empty_reparse_carries_existing_scene_and_prop(db_session, chapter, kind, binding_model, payload):
    if kind == "props":
        chapter.content += "木杖立在门边。"; db_session.commit()
    extract(db_session, chapter, [payload], kind); assert resolve(db_session, chapter, kinds=[kind])["success"]
    binding_id = db_session.query(binding_model).one().id
    extract(db_session, chapter, [], kind)
    result = resolve(db_session, chapter, kinds=[kind])
    assert result["success"] and len(result["data"]["omissions"]) == 1
    assert result["data"]["omissions"][0]["status"] == "CARRIED"
    row = db_session.query(binding_model).one()
    assert row.id == binding_id and row.resolution_method == "SOURCE_EVIDENCE_CARRY_FORWARD"
    state = binding_state(db_session, chapter.novel_id, chapter.id)["assets"][kind]
    assert state["status"] == "SUCCEEDED" and not state["emptyConfirmed"]


def test_fresh_chapter_empty_parse_does_not_carry_other_chapter_membership(db_session, chapter):
    db = db_session
    identity(db, db.query(Character).filter_by(name="刘备").one())
    extract(db, chapter, [character()]); assert resolve(db, chapter)["success"]
    second = Chapter(novel_id=chapter.novel_id, number=2, title="第二回", content=chapter.content)
    db.add(second); db.commit()
    extract(db, second, [])
    result = resolve(db, second)
    state = binding_state(db, second.novel_id, second.id)["assets"]["characters"]
    assert result["success"] and result["data"]["omissions"] == []
    assert state["status"] == "SUCCEEDED" and state["emptyConfirmed"] and state["bindings"] == []
    assert db.query(Binding).filter_by(chapter_id=chapter.id).count() == 1
    assert db.query(Binding).filter_by(chapter_id=second.id).count() == 0


def test_reconciliation_storage_failure_restores_parent_without_half_carry(db_session, chapter):
    db = db_session
    chapter.content = "刘备到桃园。关羽在园中等候。袁绍随后到场。"
    identity(db, db.query(Character).filter_by(name="刘备").one())
    guan = Character(novel_id=chapter.novel_id, name="关羽", description="关羽", appearance="关羽外观")
    db.add(guan); identity(db, guan)
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"),
                          evidenced_character("关羽", "关羽在园中等候")])
    assert resolve(db, chapter)["success"]
    before = {row.character_id: binding_snapshot(row) for row in db.query(Binding)}
    extract(db, chapter, [evidenced_character("刘备", "刘备到桃园"),
                          evidenced_character("袁绍", "袁绍随后到场")])
    def reject(mapper, connection, target):
        raise RuntimeError("binding storage failed")
    event.listen(Binding, "before_insert", reject)
    try:
        result = resolve(db, chapter)
    finally:
        event.remove(Binding, "before_insert", reject)
    assert not result["success"] and result["data"]["status"] == "FAILED"
    assert {row.character_id: binding_snapshot(row) for row in db.query(Binding)} == before
    assert not db.query(Character).filter_by(name="袁绍").first()
    assert db.query(Omission).filter_by(run_id=result["data"]["id"]).count() == 0


def test_missing_binding_is_not_valid_empty(db_session, chapter):
    identity(db_session, db_session.query(Character).filter_by(name="刘备").one())
    extract(db_session, chapter, [character()])
    assert resolve(db_session, chapter)["success"]
    db_session.query(Binding).delete()
    db_session.commit()
    state = binding_state(db_session, chapter.novel_id, chapter.id)["assets"]["characters"]
    assert state["status"] == "STALE" and not state["emptyConfirmed"]
    assert resolve(db_session, chapter)["success"]


def test_applied_binding_projection_tamper_is_stale_in_both_views(db_session, chapter):
    identity(db_session, db_session.query(Character).filter_by(name="刘备").one())
    extract(db_session, chapter, [character()])
    result = resolve(db_session, chapter)
    assert result["success"]
    run = db_session.get(Run, result["data"]["id"])
    row = db_session.query(Binding).one(); row.provenance = []; db_session.commit()
    assert resolution_response(db_session, run)["effectiveStatus"] == "STALE"
    assert binding_state(db_session, chapter.novel_id, chapter.id)["assets"]["characters"]["status"] == "STALE"


def test_empty_effective_set_still_requires_complete_ignored_decision_receipt(db_session, chapter):
    review, _, _ = groups(db_session, chapter)
    result = action(db_session, chapter, review, "IGNORE")
    run = db_session.get(Run, result["data"]["id"])
    state = binding_state(db_session, chapter.novel_id, chapter.id)["assets"]["characters"]
    assert state["status"] == "SUCCEEDED" and state["emptyConfirmed"]
    db_session.delete(db_session.get(Decision, review["id"])); db_session.commit()
    assert resolution_response(db_session, run)["effectiveStatus"] == "STALE"
    state = binding_state(db_session, chapter.novel_id, chapter.id)["assets"]["characters"]
    assert state["status"] == "STALE" and not state["emptyConfirmed"]


def test_raw_succeeded_run_with_nonterminal_decision_fails_closed(db_session, chapter):
    identity(db_session, db_session.query(Character).filter_by(name="刘备").one())
    extract(db_session, chapter, [character()])
    result = resolve(db_session, chapter)
    run = db_session.get(Run, result["data"]["id"])
    decision = db_session.query(Decision).filter_by(run_id=run.id).one()
    decision.status = "PENDING_REVIEW"; db_session.commit()
    assert run.status == "SUCCEEDED"
    assert resolution_response(db_session, run)["effectiveStatus"] == "STALE"
    assert binding_state(db_session, chapter.novel_id, chapter.id)["assets"]["characters"]["status"] == "STALE"


def test_empty_scene_prop_memberships_have_success_receipts(db_session, chapter):
    for kind in ("scenes","props"):
        extract(db_session, chapter, [], kind)
        assert resolve(db_session, chapter, kinds=[kind])["success"]
    state = binding_state(db_session, chapter.novel_id, chapter.id)
    assert state["assets"]["scenes"]["emptyConfirmed"] and state["assets"]["props"]["emptyConfirmed"]
    assert not state["phase2Ready"]  # character extraction/resolution has not happened


def test_storage_failure_rolls_back_new_assets(db_session, chapter):
    extract(db_session, chapter, [character("袁绍")])
    def reject(mapper, connection, target):
        raise RuntimeError("binding storage failed")
    event.listen(Binding, "before_insert", reject)
    try:
        result = resolve(db_session, chapter)
    finally:
        event.remove(Binding, "before_insert", reject)
    assert result["data"]["status"] == "FAILED"
    assert not db_session.query(Character).filter_by(name="袁绍").first()


def test_review_cross_book_and_catalog_revision_protected(db_session, chapter):
    review, one, _ = groups(db_session, chapter)
    original_hash = catalog(db_session, chapter.novel_id)[1]
    other = Novel(title="other")
    foreign = Character(novel=other, name="外国角色")
    db_session.add(other)
    db_session.commit()
    with pytest.raises(HTTPException):
        action(db_session, chapter, review, "MATCH", asset_id=foreign.id)
    one.description = "user changed"
    db_session.commit()
    with pytest.raises(HTTPException):
        AssetResolutionService(db_session).review(chapter.novel_id, chapter.id, review["id"],
            ReviewAction(action="IGNORE", expected_catalog_hash=original_hash))
    assert db_session.get(Decision, review["id"]).status == "PENDING_REVIEW"


def test_stale_needs_review_run_is_not_actionable(db_session, chapter):
    review, _, _ = groups(db_session, chapter)
    run = db_session.get(Run, db_session.get(Decision, review["id"]).run_id)
    db_session.get(Task, run.task_id).status = "failed"
    db_session.commit()
    assert resolution_response(db_session, run)["effectiveStatus"] == "STALE"
    assert resolution_response(db_session, run)["reviews"] == []
    with pytest.raises(HTTPException) as exc:
        action(db_session, chapter, review, "IGNORE")
    assert exc.value.status_code == 409
    assert db_session.get(Decision, review["id"]).status == "PENDING_REVIEW"


def test_migration_no_legacy_type_guessing_and_api_preview_origin(db_session, chapter):
    from migrations.add_asset_resolution import upgrade
    legacy = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(legacy, tables=[table for name, table in Base.metadata.tables.items()
                                                if name != "asset_resolution_omissions"])
        assert "asset_resolution_omissions" not in inspect(legacy).get_table_names()
        with Session(legacy) as old_db:
            old_novel = Novel(title="legacy")
            old_chapter = Chapter(novel=old_novel, number=1, title="old", content="旧正文")
            old_actor = Character(novel=old_novel, name="旧角色", appearance="旧外观")
            old_db.add(old_novel); old_db.flush()
            old_db.add(CharacterIdentity(character_id=old_actor.id, novel_id=old_novel.id, entity_type="INDIVIDUAL",
                group_size_hint=1, context={}, provenance={"origin":"LEGACY_TEST"}))
            old_db.add(Binding(novel_id=old_novel.id, chapter_id=old_chapter.id, character_id=old_actor.id,
                resolution_run_id="legacy-run", status="RESOLVED", chapter_role="BACKGROUND",
                resolution_method="LEGACY", resolution_confidence=1.0,
                source_evidence=[{"text":"旧正文"}], provenance=[]))
            old_db.commit()
        upgrade(legacy); upgrade(legacy)
        columns = {item["name"] for item in inspect(legacy).get_columns("asset_resolution_omissions")}
        assert {"run_id", "asset_type", "asset_id", "status", "proof", "proof_hash"} <= columns
        with Session(legacy) as upgraded:
            assert upgraded.query(Character).filter_by(name="旧角色").count() == 1
            assert upgraded.query(Binding).count() == 1
            assert upgraded.query(Omission).count() == 0
    finally:
        legacy.dispose()
    assert db_session.query(CharacterIdentity).count() == 0
    actor = identity(db_session, db_session.query(Character).filter_by(name="刘备").one())
    app = FastAPI(); app.include_router(router, prefix="/api/novels")
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as client:
        data = client.post(f"/api/novels/{chapter.novel_id}/asset-resolver-preview", json={
            "chapter_id":chapter.id, "asset_type":"characters", "candidate":character("玄德")}).json()["data"]
        assert data["origin"] == "MANUAL_PREVIEW" and not data["published"]
        assert data["match_type"] == "STRONG_ALIAS" and data["matched_asset_id"] == actor.id
    assert db_session.query(Binding).count() == 0


def test_phase1_api_pipeline_automatically_resolves(db_session):
    novel = Novel(title="new")
    chapter = Chapter(novel=novel, number=1, title="one", content="刘备到桃园。")
    db_session.add(novel); db_session.commit()
    result = asyncio.run(parse_and_resolve(db_session, novel.id, chapter.id, ["characters"], FakeLLM(db_session)))
    assert result["success"] and result["resolution"]["phase2Ready"]
    assert db_session.query(Binding).count() == 1


def test_stable_group_exact_match_is_code_only(db_session, chapter):
    group = Character(novel_id=chapter.novel_id, name="黄巾军", description="黄巾起义军")
    db_session.add(group); identity(db_session, group, "GROUP")
    extract(db_session, chapter, [{**character("黄巾军"), "entity_type":"GROUP", "group_size_hint":None}])
    llm = ResolverLLM(db_session)
    result = resolve(db_session, chapter, llm)
    assert result["success"] and result["data"]["decisions"][0]["matchType"] == "EXACT_NAME"
    assert not llm.calls


def test_book_wide_lease_blocks_parallel_chapter_resolution(db_session, chapter):
    second = Chapter(novel_id=chapter.novel_id, number=2, title="two", content=chapter.content)
    db_session.add(second); db_session.commit()
    extract(db_session, chapter, [character("袁绍")])
    extract(db_session, second, [character("孙坚")])
    async def parallel():
        with pytest.raises(HTTPException) as exc:
            await AssetResolutionService(db_session, ResolverLLM(db_session)).resolve(chapter.novel_id, second.id, ["characters"])
        assert exc.value.status_code == 409
    result = resolve(db_session, chapter, ResolverLLM(db_session, during=parallel))
    assert result["success"] and db_session.query(Run).count() == 1


def test_manual_match_cannot_bind_narrator(db_session, chapter):
    review, _, _ = groups(db_session, chapter)
    narrator = Character(novel_id=chapter.novel_id, name="旁白", is_narrator=True)
    db_session.add(narrator); db_session.commit()
    with pytest.raises(HTTPException) as exc:
        action(db_session, chapter, review, "MATCH", asset_id=narrator.id, confirm_legacy_type=True)
    assert exc.value.status_code == 409
    assert db_session.query(Binding).count() == 0


def test_stable_group_with_unconfirmed_explicit_scope_uses_llm(db_session, chapter):
    group = Character(novel_id=chapter.novel_id, name="黄巾军", description="东村守军")
    db_session.add(group); identity(db_session, group, "GROUP", {"location":"东村"})
    extract(db_session, chapter, [{**character("黄巾军"), "entity_type":"GROUP", "group_size_hint":None}])
    def ambiguous(data):
        target = next(row for row in data["existing_candidates"] if row["asset_id"] == group.id)
        return output("AMBIGUOUS", matches=[target], canonical="黄巾军")
    llm = ResolverLLM(db_session, ambiguous)
    result = resolve(db_session, chapter, llm)
    assert llm.calls and result["data"]["status"] == "NEEDS_REVIEW"
    assert db_session.query(Binding).count() == 0
