"""Source-grounded logical timelines. Image readiness never chooses the active appearance."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import re
from uuid import uuid4

from fastapi import HTTPException
from app.models.novel import Chapter, Character
from app.models.task import Task
from app.models.asset_resolution import (AssetResolutionRun as ResolutionRun, AssetResolutionDecision as Decision,
    ChapterCharacterBinding as Binding, ChapterCharacterAppearanceEvent as Event)
from app.models.appearance_timeline import CharacterAppearance as Appearance, AppearanceEventReview as Review, AppearanceTimelineRun as Run
from app.services.asset_resolution_service import acquire, fence, release, binding_state, current_inputs
from app.services.chapter_asset_parse_service import digest, source_hash
from app.services.appearance_locator import locate_evidence

VERSION = "appearance-timeline-v1.0.2"
TASK_TYPE = "appearance_timeline"


class TimelineFailure(Exception):
    pass


def proposal(event):
    return {"id": event.id, "chapter_id": event.chapter_id, "character_id": event.character_id,
            "candidate_id": event.candidate_id, "event_key": event.event_key, "change_type": event.change_type,
            "appearance_description": event.appearance_description, "source_evidence": event.source_evidence}


def review_snapshot(row):
    return {key: getattr(row, key) for key in ("id", "source_hash", "proposal_hash", "action", "source_start", "source_end",
                                               "evidence_text", "appearance_description", "reason")} if row else None


def chapter_basis(db, novel_id, chapter):
    state = binding_state(db, novel_id, chapter.id)["assets"]["characters"]
    if state["status"] != "SUCCEEDED":
        raise TimelineFailure(f"CHARACTER_BINDINGS_NOT_READY: chapter={chapter.id}, status={state['status']}")
    _, parsed, candidates = current_inputs(db, novel_id, chapter.id, ["characters"])
    resolution = db.get(ResolutionRun, state["runId"])
    task = db.get(Task, resolution.task_id)
    if not task or task.status != "completed":
        raise TimelineFailure("RESOLUTION_RECEIPT_UNAVAILABLE")
    by_candidate = {row.id: row for row in candidates}
    decisions = db.query(Decision).filter_by(run_id=resolution.id, asset_type="characters").order_by(Decision.id).all()
    if {row.candidate_id for row in decisions} != set(by_candidate):
        raise TimelineFailure("RESOLUTION_CANDIDATE_SET_CHANGED")
    expected_events = {}
    for decision in decisions:
        if decision.candidate != by_candidate[decision.candidate_id].payload or decision.status not in {"APPLIED", "IGNORED"}:
            raise TimelineFailure("RESOLUTION_DECISION_CHANGED")
        if decision.status == "APPLIED":
            actor = db.get(Character, decision.asset_id)
            if not actor or actor.entity_type != decision.candidate["entity_type"]:
                raise TimelineFailure("CHARACTER_IDENTITY_CHANGED")
            for item in decision.candidate["chapter_appearances"]:
                expected_events[(decision.candidate_id, item["event_key"])] = (decision.asset_id, item)
    events = db.query(Event).filter_by(chapter_id=chapter.id, resolution_run_id=resolution.id).order_by(Event.id).all()
    if {(row.candidate_id, row.event_key) for row in events} != set(expected_events):
        raise TimelineFailure("APPEARANCE_EVENT_SET_CHANGED")
    event_inputs = []
    for event in events:
        actor_id, expected = expected_events[(event.candidate_id, event.event_key)]
        if (event.novel_id != novel_id or event.character_id != actor_id or event.change_type != expected["change_type"].upper()
                or event.appearance_description != expected["appearance_description"] or event.source_evidence != expected["source_evidence"]):
            raise TimelineFailure("APPEARANCE_EVENT_PROPOSAL_CHANGED")
        p = proposal(event)
        review = db.query(Review).filter_by(event_id=event.id).order_by(Review.created_at.desc(), Review.id.desc()).first()
        if review and (review.source_hash != source_hash(chapter) or review.proposal_hash != digest(p)):
            raise TimelineFailure("EVENT_REVIEW_SOURCE_CHANGED")
        event_inputs.append({"proposal": p, "proposal_hash": digest(p), "review": review_snapshot(review)})
    return {"chapter_id": chapter.id, "number": chapter.number, "title": chapter.title, "content": chapter.content or "",
            "source_hash": source_hash(chapter), "parse_inputs": parsed, "resolution_run_id": resolution.id,
            "bindings": sorted(state["bindings"], key=lambda item: item["assetId"]), "events": event_inputs}


def collect_basis(db, novel_id, chapter_id):
    target = db.query(Chapter).filter_by(id=chapter_id, novel_id=novel_id).first()
    if not target:
        raise HTTPException(404, "章回不存在")
    chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id, Chapter.number <= target.number).order_by(Chapter.number, Chapter.id).all()
    if len({chapter.number for chapter in chapters}) != len(chapters):
        raise TimelineFailure("CHAPTER_ORDER_AMBIGUOUS")
    return {"version": VERSION, "target_chapter_id": chapter_id,
            "chapters": [chapter_basis(db, novel_id, chapter) for chapter in chapters]}


def selection_signature(selection):
    return {key: selection.get(key) for key in ("kind", "appearanceId", "sourceEventIds", "sourceChapterId")}


def unresolved(event_ids, chapter_id, reason):
    return {"kind": "UNRESOLVED", "appearanceId": None, "sourceEventIds": event_ids,
            "sourceChapterId": chapter_id, "reason": reason}


def output_current(db, result):
    if not isinstance(result, dict):
        return False
    for event_id, expected in result.get("locations", {}).items():
        row = db.get(Event, event_id)
        if not row or any(getattr(row, key) != expected[key] for key in ("source_start", "source_end", "status", "resolved_appearance_id", "location_proof", "located_source_hash")):
            return False
    for item in result.get("appearances", []):
        row = db.get(Appearance, item["id"])
        if (not row or row.definition_hash != item["definition_hash"] or row.definition != item["definition"]
                or row.description != item["description"] or row.character_id != item["character_id"]
                or row.previous_appearance_id != item["previous_appearance_id"]):
            return False
    return True


def decorate_selection(db, value, character_id):
    value = deepcopy(value)
    if value["kind"] == "APPEARANCE":
        asset = db.get(Appearance, value["appearanceId"])
        value["imageStatus"] = asset.status if asset else "MISSING_RECORD"
        value["referenceImageUrl"] = asset.reference_image_url if asset and asset.status == "READY" else None
        value["imageRevisionId"] = asset.reference_image_revision_id if asset and asset.status == "READY" else None
    elif value["kind"] == "BASE":
        actor = db.get(Character, character_id)
        value["imageStatus"] = "BASE_REFERENCE_PRESENT" if actor and actor.image_url else "NEEDS_GENERATION"
        value["referenceImageUrl"] = actor.image_url if actor else None
    return value


def timeline_response(db, run, detail=True):
    current = False
    try:
        current = (run.resolver_version == VERSION and run.input_hash == digest(run.inputs)
                   and run.input_hash == digest(collect_basis(db, run.novel_id, run.chapter_id)))
        if current and run.status in {"SUCCEEDED", "NEEDS_REVIEW"}:
            current = output_current(db, run.result)
            task = db.get(Task, run.task_id)
            metadata = json.loads(task.metadata_json or "{}") if task else {}
            current = bool(current and task and task.status == "completed"
                           and metadata.get("timeline_run_id") == run.id and metadata.get("resolver_version") == VERSION
                           and metadata.get("input_hash") == run.input_hash and metadata.get("result_hash") == digest(run.result))
    except (TimelineFailure, HTTPException, ValueError, KeyError, TypeError, AttributeError):
        current = False
    newer = db.query(Run.id).filter(Run.chapter_id == run.chapter_id, Run.created_at > run.created_at).first()
    status = "SUPERSEDED" if newer else "STALE" if run.input_hash and not current else run.status
    data = {"id": run.id, "chapterId": run.chapter_id, "taskId": run.task_id, "resolverVersion": run.resolver_version,
            "status": run.status, "effectiveStatus": status, "inputHash": run.input_hash, "sourceCurrent": current,
            "phase3Ready": status == "SUCCEEDED", "issues": run.issues, "createdAt": run.created_at.isoformat() + "Z"}
    if detail:
        result = deepcopy(run.result)
        if result:
            for chapter in result["chapters"]:
                for actor in chapter["characters"]:
                    actor["entry"] = decorate_selection(db, actor["entry"], actor["characterId"])
                    if "incoming" in actor:
                        actor["incoming"] = decorate_selection(db, actor["incoming"], actor["characterId"])
                    actor["exit"] = decorate_selection(db, actor["exit"], actor["characterId"])
                    for segment in actor["segments"]:
                        segment["selection"] = decorate_selection(db, segment["selection"], actor["characterId"])
        data.update(inputs=run.inputs, result=result)
    return data


def fail_timeline(db, run_id, message):
    db.rollback()
    run = db.get(Run, run_id)
    if not run:
        return False
    task_id = run.task_id
    changed = db.query(Run).filter_by(id=run_id, status="RUNNING").update({"status": "FAILED", "completed_at": datetime.utcnow(),
        "issues": [{"code": "TIMELINE_FAILED", "message": message}]}, synchronize_session=False)
    if changed:
        db.query(Task).filter(Task.id == task_id, Task.status.in_(["pending", "running"])).update({
            "status": "failed", "current_step": "外观时间线失败", "error_message": message, "completed_at": datetime.utcnow()}, synchronize_session=False)
        db.commit()
    db.expire_all()
    return bool(changed)


def expire_timeline_task(db, task):
    run = db.query(Run).filter_by(task_id=task.id, status="RUNNING").first()
    return fail_timeline(db, run.id, "TIMELINE_INTERRUPTED_OR_EXPIRED") if run and run.expires_at < datetime.utcnow() else False


class AppearanceTimelineService:
    def __init__(self, db):
        self.db = db

    def _definition(self, novel_id, chapter, events, previous, description, planned):
        ids = sorted(item["proposal"]["id"] for item in events)
        character_id = events[0]["proposal"]["character_id"]
        definition = {"character_id": character_id, "source_chapter_id": chapter["chapter_id"], "source_event_ids": ids,
                      "source_hash": chapter["source_hash"], "description": description,
                      "previous": selection_signature(previous),
                      "proposals": [item["proposal_hash"] for item in sorted(events, key=lambda item: item["proposal"]["id"])]}
        fingerprint = digest(definition)
        existing = self.db.query(Appearance).filter_by(definition_hash=fingerprint).first()
        for event_id in ids:
            event = self.db.get(Event, event_id)
            if event.location_proof and event.location_proof.get("definition_hash") == fingerprint:
                if not existing or event.resolved_appearance_id != existing.id:
                    raise TimelineFailure("APPEARANCE_RECORD_OR_POINTER_CHANGED")
        item = {"id": existing.id if existing else str(uuid4()), "novel_id": novel_id, "character_id": character_id,
                "source_chapter_id": chapter["chapter_id"], "source_event_id": ids[0], "definition_hash": fingerprint,
                "definition": definition, "description": description, "previous_appearance_id": previous["appearanceId"]}
        if existing and any(getattr(existing, key) != item[key] for key in ("definition", "description", "character_id", "previous_appearance_id")):
            raise TimelineFailure("APPEARANCE_DEFINITION_CHANGED")
        if fingerprint in planned:
            item = planned[fingerprint]
        else:
            planned[fingerprint] = item
        return item

    def compute(self, novel_id, basis):
        active, chapters, locations, planned = {}, [], {}, {}
        for chapter in basis["chapters"]:
            content, cid = chapter["content"], chapter["chapter_id"]
            actors = []
            for binding in chapter["bindings"]:
                aid = binding["assetId"]
                incoming = deepcopy(active.get(aid, {"kind": "BASE", "appearanceId": None, "sourceEventIds": [],
                                                     "sourceChapterId": None, "reason": "NO_PRIOR_CHANGE_VERIFIED"}))
                if incoming["kind"] == "APPEARANCE":
                    incoming["reason"] = "PREVIOUS_ACTIVE"
                entries, issues = [], []
                for item in [e for e in chapter["events"] if e["proposal"]["character_id"] == aid]:
                    p, review = item["proposal"], item["review"]
                    if review and review["action"] == "IGNORE":
                        proof = {"version": VERSION, "source_hash": chapter["source_hash"], "proposal_hash": item["proposal_hash"],
                                 "review_id": review["id"], "action": "IGNORE"}
                        locations[p["id"]] = {"source_start": None, "source_end": None, "status": "IGNORED",
                            "resolved_appearance_id": None, "location_proof": proof, "located_source_hash": chapter["source_hash"]}
                        continue
                    located = locate_evidence(content, p["source_evidence"], review)
                    effective_type = "NEW" if review and review["action"] == "CONFIRM_NEW" else p["change_type"]
                    description = review["appearance_description"] if review and review["action"] == "CONFIRM_NEW" else p["appearance_description"]
                    proof = {**located, "version": VERSION, "source_hash": chapter["source_hash"], "proposal_hash": item["proposal_hash"],
                             "review_id": review["id"] if review else None, "effective_type": effective_type}
                    locations[p["id"]] = {"source_start": located["source_start"], "source_end": located["source_end"],
                        "status": "NEEDS_REVIEW", "resolved_appearance_id": None, "location_proof": proof,
                        "located_source_hash": chapter["source_hash"]}
                    entries.append({**item, "location": located, "effective_type": effective_type, "description": description})
                    if located["status"] != "LOCATED":
                        issues.append({"code": located["code"], "eventId": p["id"]})
                located_entries = sorted([e for e in entries if e["location"]["status"] == "LOCATED"], key=lambda e: (e["location"]["source_start"], e["proposal"]["id"]))
                groups = []
                for entry in located_entries:
                    if groups:
                        prev = groups[-1][0]
                        a, b = prev["location"], entry["location"]
                        if b["source_start"] < a["source_end"]:
                            if (a["source_start"], a["source_end"], prev["effective_type"], prev["description"]) == (b["source_start"], b["source_end"], entry["effective_type"], entry["description"]):
                                groups[-1].append(entry)
                                continue
                            issues.append({"code": "OVERLAPPING_APPEARANCE_EVENTS", "eventId": entry["proposal"]["id"]})
                    groups.append([entry])
                if issues:
                    incoming = unresolved([e["proposal"]["id"] for e in entries], cid, "EVENT_LOCATION_REVIEW")
                    segments = [{"start": 0, "end": len(content), "selection": deepcopy(incoming)}]
                    current = incoming
                else:
                    current, cursor, segments = deepcopy(incoming), 0, []
                    for group in groups:
                        item = group[0]
                        start = item["location"]["source_start"]
                        if start > cursor:
                            segments.append({"start": cursor, "end": start, "selection": deepcopy(current)})
                        event_ids = sorted(e["proposal"]["id"] for e in group)
                        if item["effective_type"] == "UNCERTAIN":
                            current = unresolved(event_ids, cid, "UNCERTAIN_EVENT")
                            issues.append({"code": "UNCERTAIN_EVENT", "eventIds": event_ids})
                        elif current["kind"] == "UNRESOLVED":
                            issues.append({"code": "UPSTREAM_APPEARANCE_UNRESOLVED", "eventIds": event_ids})
                        else:
                            asset = self._definition(novel_id, chapter, group, current, item["description"], planned)
                            current = {"kind": "APPEARANCE", "appearanceId": asset["id"], "sourceEventIds": event_ids,
                                       "sourceChapterId": cid, "reason": "NEW_EVENT"}
                            for event_id in event_ids:
                                locations[event_id]["status"] = "RESOLVED"
                                locations[event_id]["resolved_appearance_id"] = asset["id"]
                                locations[event_id]["location_proof"]["definition_hash"] = asset["definition_hash"]
                        cursor = start
                    if cursor < len(content):
                        segments.append({"start": cursor, "end": len(content), "selection": deepcopy(current)})
                if current["kind"] == "UNRESOLVED" and not issues:
                    issues.append({"code": "UPSTREAM_APPEARANCE_UNRESOLVED", "eventIds": current["sourceEventIds"]})
                active[aid] = deepcopy(current)
                actors.append({"characterId": aid, "name": binding["name"], "bindingId": binding["id"],
                    "incoming": incoming, "entry": deepcopy(segments[0]["selection"]), "exit": deepcopy(current), "segments": segments, "issues": issues,
                    "logicalReady": not any(s["selection"]["kind"] == "UNRESOLVED" for s in segments)})
            chapters.append({"chapterId": cid, "number": chapter["number"], "sourceHash": chapter["source_hash"],
                             "length": len(content), "characters": actors})
        target = next(item for item in chapters if item["chapterId"] == basis["target_chapter_id"])
        return {"targetChapterId": basis["target_chapter_id"], "offsetUnit": "UNICODE_CODE_POINT", "endExclusive": True,
                "chapters": chapters, "locations": locations, "appearances": list(planned.values()),
                "logicalReady": all(actor["logicalReady"] for actor in target["characters"])}

    def build(self, novel_id, chapter_id, force=False):
        db = self.db
        from app.services.rebuild_context import stage_parent
        parent_task_id = stage_parent(db, chapter_id)
        target = db.query(Chapter).filter_by(id=chapter_id, novel_id=novel_id).first()
        if not target:
            raise HTTPException(404, "章回不存在")
        old = db.query(Run).filter_by(chapter_id=chapter_id).order_by(Run.created_at.desc(), Run.id.desc()).first()
        if old and not force:
            data = timeline_response(db, old)
            if data["effectiveStatus"] in {"SUCCEEDED", "NEEDS_REVIEW"}:
                return {"success": data["phase3Ready"], "data": data, "reused": True}
        run_id, task_id = str(uuid4()), str(uuid4())
        acquire(db, novel_id, run_id, 300)
        try:
            run = Run(id=run_id, novel_id=novel_id, chapter_id=chapter_id, task_id=task_id, resolver_version=VERSION,
                      status="RUNNING", expires_at=datetime.utcnow() + timedelta(seconds=300))
            task = Task(id=task_id, novel_id=novel_id, chapter_id=chapter_id, type=TASK_TYPE, status="running", parent_task_id=parent_task_id,
                        name=f"外观事件定位与时间线 · 第{target.number}回", current_step="核验前置角色关联",
                        started_at=datetime.utcnow(), metadata_json=json.dumps({"execution_purpose": "production", "timeline_run_id": run_id, "resolver_version": VERSION}))
            db.add_all([run, task]); db.commit()
            try:
                basis = collect_basis(db, novel_id, chapter_id)
                run.inputs, run.input_hash = basis, digest(basis)
                db.commit()
                result = self.compute(novel_id, basis)
                db.expire_all()
                fence(db, novel_id, run_id)
                stage_parent(db, chapter_id)
                if digest(collect_basis(db, novel_id, chapter_id)) != digest(basis):
                    raise TimelineFailure("TIMELINE_SOURCE_CHANGED")
                run, task = db.get(Run, run_id), db.get(Task, task_id)
                if not run or not task or run.status != "RUNNING" or task.status != "running":
                    raise TimelineFailure("TIMELINE_TASK_CHANGED")
                for item in result["appearances"]:
                    if not db.get(Appearance, item["id"]):
                        db.add(Appearance(**item, status="NEEDS_GENERATION"))
                for event_id, values in result["locations"].items():
                    event = db.get(Event, event_id)
                    for key, value in values.items():
                        setattr(event, key, deepcopy(value))
                run.result = result
                run.status = "SUCCEEDED" if result["logicalReady"] else "NEEDS_REVIEW"
                run.issues = [issue for item in result["chapters"] if item["chapterId"] == chapter_id for actor in item["characters"] for issue in actor["issues"]]
                run.completed_at = datetime.utcnow()
                task.status, task.progress, task.completed_at = "completed", 100, datetime.utcnow()
                task.metadata_json = json.dumps({"execution_purpose": "production", "timeline_run_id": run.id,
                    "resolver_version": VERSION, "input_hash": run.input_hash, "result_hash": digest(result)}, ensure_ascii=False)
                task.current_step = "逻辑时间线已就绪，图片状态独立" if run.status == "SUCCEEDED" else "外观事件或继承需检查"
                db.commit()
            except Exception as exc:
                fail_timeline(db, run_id, str(exc))
        finally:
            release(db, novel_id, run_id)
        db.expire_all()
        data = timeline_response(db, db.get(Run, run_id))
        return {"success": data["phase3Ready"], "data": data}

    def review(self, novel_id, chapter_id, event_id, data):
        db, owner = self.db, str(uuid4())
        acquire(db, novel_id, owner, 120)
        try:
            fence(db, novel_id, owner)
            chapter = db.query(Chapter).filter_by(id=chapter_id, novel_id=novel_id).first()
            if not chapter:
                raise HTTPException(404, "章回不存在")
            basis = chapter_basis(db, novel_id, chapter)
            item = next((e for e in basis["events"] if e["proposal"]["id"] == event_id), None)
            if not item:
                raise HTTPException(404, "当前角色关联中没有该事件")
            if data.expected_source_hash != basis["source_hash"] or data.expected_proposal_hash != item["proposal_hash"]:
                raise HTTPException(409, "原文或事件提议已变化，请刷新")
            if data.action != "IGNORE":
                try:
                    located = locate_evidence(chapter.content, item["proposal"]["source_evidence"], data.model_dump())
                    if located["status"] != "LOCATED":
                        raise ValueError("MANUAL_LOCATION_NOT_SUPPORTED_BY_SOURCE")
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
            if data.appearance_description and re.search(r"躺在|躺下|坐在|坐下|站在|跪在|跪下|跑向|走到|手持|拿着|骑着", data.appearance_description):
                raise HTTPException(422, "外观描述应只包含持续造型变化")
            row = Review(event_id=event_id, source_hash=basis["source_hash"], proposal_hash=item["proposal_hash"],
                         **data.model_dump(exclude={"expected_source_hash", "expected_proposal_hash"}))
            db.add(row); db.commit()
            review_id = row.id
        finally:
            release(db, novel_id, owner)
        result = self.build(novel_id, chapter_id)
        return {"success": True, "reviewId": review_id, "timeline": result}

    def at(self, novel_id, chapter_id, character_id, offset):
        run = self.db.query(Run).filter_by(novel_id=novel_id, chapter_id=chapter_id).order_by(Run.created_at.desc(), Run.id.desc()).first()
        if not run:
            raise HTTPException(409, "TIMELINE_REQUIRED")
        data = timeline_response(self.db, run)
        if data["effectiveStatus"] not in {"SUCCEEDED", "NEEDS_REVIEW"}:
            raise HTTPException(409, f"TIMELINE_NOT_CURRENT: {data['effectiveStatus']}")
        target = next(item for item in data["result"]["chapters"] if item["chapterId"] == chapter_id)
        if type(offset) is not int or not 0 <= offset < target["length"]:
            raise HTTPException(422, "source_start超出原文范围")
        actor = next((item for item in target["characters"] if item["characterId"] == character_id), None)
        if not actor:
            raise HTTPException(409, "CHARACTER_NOT_BOUND_TO_CHAPTER")
        segment = next(item for item in actor["segments"] if item["start"] <= offset < item["end"])
        return {"timelineRunId": run.id, "characterId": character_id, "logicalReady": segment["selection"]["kind"] != "UNRESOLVED", **segment}

    def rebuild_through(self, novel_id, chapter_id):
        target = self.db.query(Chapter).filter_by(id=chapter_id, novel_id=novel_id).first()
        if not target:
            raise HTTPException(404, "章回不存在")
        ids = [row.id for row in self.db.query(Chapter).filter(Chapter.novel_id == novel_id, Chapter.number <= target.number).order_by(Chapter.number, Chapter.id)]
        results = [self.build(novel_id, cid) for cid in ids]
        return {"success": all(item["success"] for item in results), "data": [item["data"] for item in results]}
