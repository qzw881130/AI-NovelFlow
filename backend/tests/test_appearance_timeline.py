"""Exact locations and logical inheritance; no image/model execution is used for the timeline."""
from copy import deepcopy
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.models.novel import Novel, Chapter, Character
from app.models.task import Task
from app.models.asset_resolution import ChapterCharacterAppearanceEvent as Event
from app.models.appearance_timeline import CharacterAppearance as Appearance, AppearanceTimelineRun as Run, AppearanceEventReview
from app.services.appearance_locator import locate_evidence
from app.services.appearance_timeline_service import AppearanceTimelineService, timeline_response, proposal
from app.services.chapter_asset_parse_service import digest, source_hash
from app.schemas.appearance_timeline import AppearanceReviewRequest
from test_asset_resolution import db_session, chapter, identity, extract, resolve, ResolverLLM, row_snapshot
from test_chapter_asset_parse import character, FakeLLM, execute


def change(text, description="全身铠甲", key="appearance_1", kind="new"):
    return {"event_key": key, "change_type": kind, "appearance_description": description, "source_evidence": [{"text": text}]}


def prepare(db, chapter, text, changes=None, name="刘备", empty=False):
    chapter.content = text
    db.commit()
    actor = db.query(Character).filter_by(novel_id=chapter.novel_id, name=name).first()
    if actor and not actor.entity_type:
        identity(db, actor)
    payload = {**character(name), "source_evidence": [{"text": text}], "chapter_appearances": changes or []}
    extract(db, chapter, [] if empty else [payload])
    result = resolve(db, chapter)
    assert result["success"], result
    return db.query(Character).filter_by(novel_id=chapter.novel_id, name=name).first()


def next_chapter(db, previous, number, text, changes=None, empty=False):
    chapter = Chapter(novel_id=previous.novel_id, number=number, title=f"第{number}回", content=text)
    db.add(chapter); db.commit()
    prepare(db, chapter, text, changes, empty=empty)
    return chapter


def target(result, chapter_id):
    return next(item for item in result["data"]["result"]["chapters"] if item["chapterId"] == chapter_id)


def review(db, chapter, row, action, start=None, end=None, description=None):
    data = AppearanceReviewRequest(action=action, expected_source_hash=source_hash(chapter), expected_proposal_hash=digest(proposal(row)),
        source_start=start, source_end=end, evidence_text=chapter.content[start:end] if start is not None else None,
        appearance_description=description, reason="explicit test review")
    return AppearanceTimelineService(db).review(chapter.novel_id, chapter.id, row.id, data)


def test_unicode_offsets_preserve_crlf_and_original_bytes():
    content = "🐺\r\n玄德披甲。\r\n结束"
    result = locate_evidence(content, [{"text": "玄德披甲"}])
    assert result["status"] == "LOCATED"
    assert result["source_start"] == 3 and result["source_end"] == 7
    assert content[result["source_start"]:result["source_end"]] == "玄德披甲"
    assert result["offsetUnit"] == "UNICODE_CODE_POINT"


@pytest.mark.parametrize("content,evidence,code", [
    ("披甲后披甲", [{"text":"披甲"}], "AMBIGUOUS_SOURCE"),
    ("刘备披甲", [{"text":"刘备 披甲"}], "EVIDENCE_NOT_FOUND"),
    ("披甲。远处换袍。", [{"text":"披甲"},{"text":"换袍"}], "DISJOINT_EVIDENCE"),
])
def test_locator_never_picks_first_or_fabricates_positions(content, evidence, code):
    result = locate_evidence(content, evidence)
    assert result["status"] == "NEEDS_REVIEW" and result["code"] == code
    assert result["source_start"] is None and result["source_end"] is None


def test_more_precise_evidence_disambiguates_repeated_quote():
    content = "先披甲。后来他再次披甲出门。"
    result = locate_evidence(content, [{"text":"披甲"},{"text":"再次披甲出门"}])
    assert result["status"] == "LOCATED" and result["source_start"] == content.index("披甲出门")


def test_base_then_multiple_new_changes_are_contiguous(db_session, chapter):
    text = "🐺刘备出门。刘备披甲。稍后刘备换袍。"
    actor = prepare(db_session, chapter, text, [change("刘备披甲"), change("刘备换袍", "官服", "appearance_2")])
    before = row_snapshot(actor)
    service = AppearanceTimelineService(db_session)
    result = service.build(chapter.novel_id, chapter.id)
    assert result["success"], result
    item = target(result, chapter.id)["characters"][0]
    segments = item["segments"]
    starts = [0, text.index("刘备披甲"), text.index("刘备换袍")]
    assert [(s["start"], s["end"]) for s in segments] == list(zip(starts, starts[1:] + [len(text)]))
    assert [s["selection"]["kind"] for s in segments] == ["BASE", "APPEARANCE", "APPEARANCE"]
    first, second = [db_session.get(Appearance, s["selection"]["appearanceId"]) for s in segments[1:]]
    assert second.previous_appearance_id == first.id
    assert first.status == second.status == "NEEDS_GENERATION"
    assert service.at(chapter.novel_id, chapter.id, actor.id, starts[1]-1)["selection"]["kind"] == "BASE"
    assert service.at(chapter.novel_id, chapter.id, actor.id, starts[1])["selection"]["appearanceId"] == first.id
    for row in db_session.query(Event):
        assert text[row.source_start:row.source_end] == row.location_proof["matched_text"]
        assert row.status == "RESOLVED"
    db_session.refresh(actor)
    assert row_snapshot(actor) == before
    again = service.build(chapter.novel_id, chapter.id)
    assert again["reused"] and again["data"]["id"] == result["data"]["id"]


@pytest.mark.parametrize("image_status", ["NEEDS_GENERATION","FAILED","REJECTED","READY"])
def test_next_chapter_inherits_latest_logical_not_latest_ready(db_session, chapter, image_status):
    actor = prepare(db_session, chapter, "刘备披甲。刘备换袍。", [change("刘备披甲"), change("刘备换袍", "官服", "appearance_2")])
    next_c = next_chapter(db_session, chapter, 2, "刘备再次出场，没有换装。")
    service = AppearanceTimelineService(db_session)
    result = service.build(chapter.novel_id, next_c.id)
    assert result["success"]
    current = target(result, next_c.id)["characters"][0]["entry"]
    assert current["kind"] == "APPEARANCE" and current["reason"] == "PREVIOUS_ACTIVE"
    latest = db_session.get(Appearance, current["appearanceId"])
    earlier = db_session.get(Appearance, latest.previous_appearance_id)
    earlier.status, earlier.reference_image_url = "READY", "/older-image.png"
    latest.status = image_status
    db_session.commit()
    again = service.build(chapter.novel_id, next_c.id)
    assert again["reused"]
    chosen = service.at(chapter.novel_id, next_c.id, actor.id, 0)
    assert chosen["logicalReady"] and chosen["selection"]["appearanceId"] == latest.id
    assert chosen["selection"]["imageStatus"] == image_status


def test_confirmed_absence_in_middle_chapter_preserves_active_appearance(db_session, chapter):
    actor = prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    next_chapter(db_session, chapter, 2, "风吹树林。", empty=True)
    third = next_chapter(db_session, chapter, 3, "刘备来到营中。")
    result = AppearanceTimelineService(db_session).build(chapter.novel_id, third.id)
    assert result["success"]
    entry = target(result, third.id)["characters"][0]["entry"]
    assert entry["reason"] == "PREVIOUS_ACTIVE" and entry["sourceChapterId"] == chapter.id


def test_missing_prior_bindings_cannot_become_base(db_session, chapter):
    second = next_chapter(db_session, chapter, 2, "刘备走过桃园。")
    result = AppearanceTimelineService(db_session).build(chapter.novel_id, second.id)
    assert not result["success"] and result["data"]["status"] == "FAILED"
    assert "CHARACTER_BINDINGS_NOT_READY" in result["data"]["issues"][0]["message"]
    assert db_session.query(Appearance).count() == 0


def test_uncertain_blocks_only_after_known_position_and_propagates(db_session, chapter):
    text = "刘备到营中。刘备整装待发。"
    actor = prepare(db_session, chapter, text, [change("刘备整装待发", None, kind="uncertain")])
    second = next_chapter(db_session, chapter, 2, "刘备继续前进。")
    service = AppearanceTimelineService(db_session)
    first = service.build(chapter.novel_id, chapter.id)
    assert first["data"]["status"] == "NEEDS_REVIEW"
    assert service.at(chapter.novel_id, chapter.id, actor.id, 0)["selection"]["kind"] == "BASE"
    assert not service.at(chapter.novel_id, chapter.id, actor.id, text.index("刘备整装"))["logicalReady"]
    later = service.build(chapter.novel_id, second.id)
    assert not later["success"] and target(later, second.id)["characters"][0]["entry"]["kind"] == "UNRESOLVED"
    assert db_session.query(Appearance).count() == 0
    event_row = db_session.query(Event).one()
    review(db_session, chapter, event_row, "IGNORE")
    old = timeline_response(db_session, db_session.get(Run, later["data"]["id"]))
    assert old["effectiveStatus"] == "STALE"
    rebuilt = service.build(chapter.novel_id, second.id)
    assert rebuilt["success"] and target(rebuilt, second.id)["characters"][0]["entry"]["kind"] == "BASE"


def test_repeated_quote_manual_location_and_uncertain_confirmation(db_session, chapter):
    text = "刘备整装。歇息后，刘备整装。"
    actor = prepare(db_session, chapter, text, [change("刘备整装", None, kind="uncertain")])
    service = AppearanceTimelineService(db_session)
    result = service.build(chapter.novel_id, chapter.id)
    assert not result["success"]
    assert target(result, chapter.id)["characters"][0]["entry"]["kind"] == "UNRESOLVED"
    row = db_session.query(Event).one()
    start = text.rindex("刘备整装")
    result = review(db_session, chapter, row, "CONFIRM_NEW", start, start+len("刘备整装"), "穿上作战铠甲")
    assert result["timeline"]["success"]
    assert service.at(chapter.novel_id, chapter.id, actor.id, start)["selection"]["kind"] == "APPEARANCE"
    assert db_session.query(AppearanceEventReview).count() == 1
    assert row.change_type == "UNCERTAIN"  # original model proposal retained


def test_overlapping_conflicting_events_do_not_pick_last(db_session, chapter):
    text = "刘备披甲，稍后换袍。"
    prepare(db_session, chapter, text, [change(text), change("稍后换袍", "官服", "appearance_2")])
    result = AppearanceTimelineService(db_session).build(chapter.novel_id, chapter.id)
    assert not result["success"]
    assert result["data"]["issues"][0]["code"] == "OVERLAPPING_APPEARANCE_EVENTS"
    assert db_session.query(Appearance).count() == 0


def test_same_identity_alias_events_coalesce(db_session, chapter):
    chapter.content = "刘备字玄德，刘备披甲。"; db_session.commit()
    actor = identity(db_session, db_session.query(Character).filter_by(name="刘备").one())
    payloads = [{**character(name), "source_evidence":[{"text":chapter.content}],
                 "chapter_appearances":[change("刘备披甲")]} for name in ("刘备","玄德")]
    extract(db_session, chapter, payloads); assert resolve(db_session, chapter)["success"]
    result = AppearanceTimelineService(db_session).build(chapter.novel_id, chapter.id)
    assert result["success"] and db_session.query(Appearance).count() == 1
    events = db_session.query(Event).all()
    assert len(events) == 2 and events[0].resolved_appearance_id == events[1].resolved_appearance_id
    assert len(target(result, chapter.id)["characters"][0]["exit"]["sourceEventIds"]) == 2


def test_source_edit_invalidates_dependent_timeline(db_session, chapter):
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    second = next_chapter(db_session, chapter, 2, "刘备继续前进。")
    service = AppearanceTimelineService(db_session)
    result = service.build(chapter.novel_id, second.id)
    chapter.content += "新增原文。"; db_session.commit()
    assert timeline_response(db_session, db_session.get(Run, result["data"]["id"]))["effectiveStatus"] == "STALE"
    with pytest.raises(HTTPException):
        service.at(chapter.novel_id, second.id, db_session.query(Character).filter_by(name="刘备").one().id, 0)


def test_missing_appearance_record_does_not_fallback_or_recreate(db_session, chapter):
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    service = AppearanceTimelineService(db_session)
    assert service.build(chapter.novel_id, chapter.id)["success"]
    db_session.query(Appearance).delete(); db_session.commit()
    result = service.build(chapter.novel_id, chapter.id)
    assert result["data"]["status"] == "FAILED" and db_session.query(Appearance).count() == 0


def test_source_changes_during_compute_prevent_publish(db_session, chapter, monkeypatch):
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    service = AppearanceTimelineService(db_session)
    compute = service.compute
    def changed(*args):
        result = compute(*args)
        chapter.content += "改动"; db_session.commit()
        return result
    monkeypatch.setattr(service, "compute", changed)
    result = service.build(chapter.novel_id, chapter.id)
    assert not result["success"] and db_session.query(Appearance).count() == 0
    assert db_session.query(Event).one().source_start is None


def test_storage_failure_rolls_back_appearance_and_locations(db_session, chapter):
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    def reject(mapper, connection, target):
        raise RuntimeError("appearance insert failed")
    event.listen(Appearance, "before_insert", reject)
    try:
        result = AppearanceTimelineService(db_session).build(chapter.novel_id, chapter.id)
    finally:
        event.remove(Appearance, "before_insert", reject)
    assert result["data"]["status"] == "FAILED"
    assert db_session.query(Appearance).count() == 0 and db_session.query(Event).one().source_start is None


def test_manual_review_rejects_wrong_source_hash_and_span(db_session, chapter):
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    row = db_session.query(Event).one()
    service = AppearanceTimelineService(db_session)
    data = AppearanceReviewRequest(action="LOCATE", expected_source_hash="wrong", expected_proposal_hash=digest(proposal(row)),
                                   source_start=0, source_end=2, evidence_text="刘备", reason="test")
    with pytest.raises(HTTPException):
        service.review(chapter.novel_id, chapter.id, row.id, data)
    data.expected_source_hash = source_hash(chapter)
    data.evidence_text = "伪造"
    with pytest.raises(HTTPException):
        service.review(chapter.novel_id, chapter.id, row.id, data)
    assert db_session.query(AppearanceEventReview).count() == 0


def test_scene_ambiguity_does_not_block_character_timeline(db_session, chapter):
    identity(db_session, db_session.query(Character).filter_by(name="刘备").one())
    outputs = {"characters":{"characters":[character()]}, "scenes":{"scenes":[{
        "name":"林中小径", "description":"小径", "setting":"树木", "source_evidence":[{"text":"刘备到桃园"}]}]}}
    assert execute(db_session, chapter, FakeLLM(db_session, outputs), ["characters","scenes"])["success"]
    def scene_review(data):
        item = data["existing_candidates"][0]
        return {"resolution":"AMBIGUOUS","matched_asset_id":None,"canonical_name":"林中小径","confidence":0.4,
                "match_type":"AMBIGUOUS","needs_review":True,"candidate_matches":[{"asset_id":item["asset_id"],"canonical_name":item["canonical_name"],"confidence":0.4}],"reason":"needs review"}
    result = resolve(db_session, chapter, ResolverLLM(db_session, scene_review), ["characters","scenes"])
    assert result["data"]["status"] == "NEEDS_REVIEW"
    assert AppearanceTimelineService(db_session).build(chapter.novel_id, chapter.id)["success"]


def test_duplicate_chapter_order_blocks_inheritance(db_session, chapter):
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    duplicate = Chapter(novel_id=chapter.novel_id, number=chapter.number, title="duplicate", content="text")
    db_session.add(duplicate); db_session.commit()
    result = AppearanceTimelineService(db_session).build(chapter.novel_id, chapter.id)
    assert result["data"]["status"] == "FAILED"
    assert "CHAPTER_ORDER_AMBIGUOUS" in result["data"]["issues"][0]["message"]


def test_current_event_set_must_match_phase2_proposals(db_session, chapter):
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    db_session.query(Event).delete(); db_session.commit()
    result = AppearanceTimelineService(db_session).build(chapter.novel_id, chapter.id)
    assert result["data"]["status"] == "FAILED" and db_session.query(Appearance).count() == 0
    assert "APPEARANCE_EVENT_SET_CHANGED" in result["data"]["issues"][0]["message"]


def test_point_lookup_checks_character_and_range(db_session, chapter):
    actor = prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    service = AppearanceTimelineService(db_session)
    assert service.build(chapter.novel_id, chapter.id)["success"]
    for offset in (-1, len(chapter.content)):
        with pytest.raises(HTTPException):
            service.at(chapter.novel_id, chapter.id, actor.id, offset)
    with pytest.raises(HTTPException):
        service.at(chapter.novel_id, chapter.id, "unbound-id", 0)


def test_migration_idempotent_leaves_unlocated_events_unchanged(db_session, chapter):
    from app.services.appearance_timeline_schema import upgrade
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    upgrade(db_session.get_bind()); upgrade(db_session.get_bind())
    row = db_session.query(Event).one()
    assert row.status == "PENDING_LOCATION" and row.source_start is None and row.resolved_appearance_id is None
    assert db_session.query(Appearance).count() == 0


def test_event_at_zero_is_effective_at_chapter_entry(db_session, chapter):
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    result = AppearanceTimelineService(db_session).build(chapter.novel_id, chapter.id)
    actor = target(result, chapter.id)["characters"][0]
    assert actor["incoming"]["kind"] == "BASE"
    assert actor["entry"]["kind"] == "APPEARANCE"


@pytest.mark.parametrize("damage", ["result", "input", "task_metadata"])
def test_frozen_snapshot_integrity_is_checked_before_lookup(db_session, chapter, damage):
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    service = AppearanceTimelineService(db_session)
    result = service.build(chapter.novel_id, chapter.id)
    run = db_session.get(Run, result["data"]["id"])
    if damage == "result":
        data = deepcopy(run.result)
        data["chapters"][0]["characters"][0]["segments"][0]["selection"]["kind"] = "BASE"
        run.result = data
    elif damage == "input":
        data = deepcopy(run.inputs); data["chapters"][0]["content"] = "changed"; run.inputs = data
    else:
        db_session.get(Task, run.task_id).metadata_json = "invalid-json"
    db_session.commit()
    assert not timeline_response(db_session, run)["phase3Ready"]
    with pytest.raises(HTTPException):
        service.at(chapter.novel_id, chapter.id, db_session.query(Character).filter_by(name="刘备").one().id, 0)


def test_review_creates_new_logical_definition_without_overwriting_ready_asset(db_session, chapter):
    prepare(db_session, chapter, "刘备披甲。", [change("刘备披甲")])
    service = AppearanceTimelineService(db_session)
    first = service.build(chapter.novel_id, chapter.id)
    old_id = target(first, chapter.id)["characters"][0]["entry"]["appearanceId"]
    old = db_session.get(Appearance, old_id)
    old.status, old.reference_image_url = "READY", "/accepted-appearance.png"
    db_session.commit()
    row = db_session.query(Event).one()
    result = review(db_session, chapter, row, "CONFIRM_NEW", 0, len("刘备披甲"), "穿上红色铠甲")
    new_id = target(result["timeline"], chapter.id)["characters"][0]["entry"]["appearanceId"]
    assert new_id != old_id
    db_session.refresh(old)
    assert (old.description, old.status, old.reference_image_url) == ("全身铠甲", "READY", "/accepted-appearance.png")
    assert db_session.get(Appearance, new_id).status == "NEEDS_GENERATION"
