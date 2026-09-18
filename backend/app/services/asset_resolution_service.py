"""Phase2 identity decisions and atomic official memberships."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from time import perf_counter
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.novel import Novel, Chapter, Character
from app.models.task import Task
from app.models.llm_log import LLMLog
from app.models.chapter_asset_parse import ChapterAssetParseRun as ParseRun, ChapterAssetCandidate as Candidate
from app.models.asset_resolution import (AssetResolutionRun as Run, AssetResolutionDecision as Decision,
    AssetResolutionOmission as Omission, AssetResolutionLease as Lease, CharacterIdentity, CharacterAlias,
    ChapterCharacterAppearanceEvent as AppearanceEvent)
from app.schemas.asset_resolution import ResolveRequest, parse_resolution
from app.schemas.chapter_asset_parse import validate_output
from app.services.chapter_asset_parse_service import source_hash, request_template_current, digest, PARSER_VERSION
from app.services.llm_service import LLMService
from app.services.asset_identity import (MODELS, BINDINGS, load_policy, catalog, compatible, retrieve,
                                        deterministic, seed_aliases, context_excerpt)

VERSION = "asset-resolver-v1.1.0"
TASK_TYPE = "chapter_asset_resolution"
OMISSION_VERSION = "chapter-asset-omission-v1"
EVENT_PROVENANCE_ISSUES = {"PARENT_APPEARANCE_EVENT_SET_CHANGED", "PARENT_APPEARANCE_EVENT_CHANGED"}


class ResolutionFailure(Exception):
    pass


def _serialized(value):
    return value.isoformat() if hasattr(value, "isoformat") else deepcopy(value)


def _binding_snapshot(row, fk):
    return {column.key: _serialized(getattr(row, column.key)) for column in row.__table__.columns}


def _parse_inputs_equal(left, right, kinds):
    return left.get("source_hash") == right.get("source_hash") and all(
        left.get("kinds", {}).get(kind) == right.get("kinds", {}).get(kind) for kind in kinds)


def _pending_kind(db, run_id, kind):
    return bool(
        db.query(Decision.id).filter_by(run_id=run_id, asset_type=kind).filter(
            Decision.status.notin_(["APPLIED", "IGNORED"])).first()
        or db.query(Omission.id).filter_by(run_id=run_id, asset_type=kind, status="PENDING_REVIEW").first()
    )


def _carried_ids(db, run_id, kind):
    return {row.asset_id for row in db.query(Omission).filter_by(run_id=run_id, asset_type=kind, status="CARRIED")}


def omission_response(row):
    return {"id": row.id, "assetType": row.asset_type, "assetId": row.asset_id,
            "priorBindingId": row.prior_binding_id, "priorResolutionRunId": row.prior_resolution_run_id,
            "status": row.status, "reasonCode": row.reason_code, "proof": row.proof,
            "proofHash": row.proof_hash, "createdAt": row.created_at.isoformat() + "Z"}


def _evidence_spans(content, evidence):
    spans = []
    for quote in evidence or []:
        text = quote.get("text") if isinstance(quote, dict) else None
        if not text:
            continue
        cursor = 0
        while True:
            start = content.find(text, cursor)
            if start < 0:
                break
            spans.append((start, start + len(text)))
            cursor = start + 1
    return spans


def _overlapping_evidence(content, left, right):
    return any(a < d and c < b for a, b in _evidence_spans(content, left)
               for c, d in _evidence_spans(content, right))


def current_inputs(db, novel_id, chapter_id, kinds):
    chapter = db.query(Chapter).filter_by(id=chapter_id, novel_id=novel_id).populate_existing().first()
    if not chapter:
        raise HTTPException(404, "章回不存在")
    runs = db.query(ParseRun).filter_by(novel_id=novel_id, chapter_id=chapter_id).order_by(ParseRun.created_at.desc(), ParseRun.id.desc()).populate_existing().all()
    selected = {kind: next((run for run in runs if kind in run.kinds), None) for kind in kinds}
    records, candidates = {}, []
    for kind, run in selected.items():
        if (not run or run.status != "SUCCEEDED" or run.parser_version != PARSER_VERSION
                or run.source_hash != source_hash(chapter) or not request_template_current(run)):
            raise HTTPException(409, f"PHASE1_NOT_READY: {kind}必须使用当前原文、当前版本的最新成功候选")
        task = db.get(Task, run.task_id)
        calls = [call for call in run.calls if call["assetType"] == kind]
        if not task or task.status != "completed" or len(calls) != 1:
            raise HTTPException(409, "PHASE1_PROVENANCE_UNAVAILABLE")
        call = calls[0]
        log = db.get(LLMLog, call["llmLogId"])
        if (not log or log.status != "success" or log.novel_id != novel_id or log.chapter_id != chapter_id
                or log.response != call["response"] or log.system_prompt != call["systemPrompt"] or log.user_prompt != call["userPrompt"]):
            raise HTTPException(409, "PHASE1_LOG_CHANGED")
        expected = validate_output(kind, call["response"])
        rows = db.query(Candidate).filter_by(run_id=run.id, asset_type=kind).order_by(Candidate.name).populate_existing().all()
        if (any(row.validation_status != "VALIDATED" or row.issues or row.name != row.payload["name"] for row in rows)
                or digest(sorted(expected, key=lambda item: item["name"])) != digest([row.payload for row in rows])):
            raise HTTPException(409, "PHASE1_CANDIDATE_CHANGED")
        records[kind] = {"parse_run_id": run.id, "source_hash": run.source_hash,
                         "candidates": [{"id": row.id, "hash": digest(row.payload)} for row in rows]}
        candidates.extend(rows)
    return chapter, {"source_hash": source_hash(chapter), "kinds": records}, candidates


def _validated_parent_parse(db, run, kind):
    issues = []
    info = (run.inputs.get("kinds") or {}).get(kind) if isinstance(run.inputs, dict) else None
    parse_run = db.get(ParseRun, info.get("parse_run_id")) if isinstance(info, dict) else None
    rows = []
    if not parse_run or parse_run.novel_id != run.novel_id or parse_run.chapter_id != run.chapter_id:
        issues.append("PARENT_PARSE_RUN_MISSING")
        return parse_run, {}, issues
    if parse_run.status != "SUCCEEDED" or parse_run.source_hash != info.get("source_hash"):
        issues.append("PARENT_PARSE_RUN_INVALID")
    task = db.get(Task, parse_run.task_id)
    calls = [call for call in parse_run.calls if call.get("assetType") == kind]
    if not task or task.status != "completed" or len(calls) != 1:
        issues.append("PARENT_PARSE_RECEIPT_UNAVAILABLE")
    else:
        call = calls[0]
        log = db.get(LLMLog, call.get("llmLogId")) if call.get("llmLogId") else None
        if (not log or log.status != "success" or log.novel_id != run.novel_id or log.chapter_id != run.chapter_id
                or log.response != call.get("response") or log.system_prompt != call.get("systemPrompt")
                or log.user_prompt != call.get("userPrompt")):
            issues.append("PARENT_PARSE_LOG_CHANGED")
        else:
            try:
                expected = validate_output(kind, call["response"])
                rows = db.query(Candidate).filter_by(run_id=parse_run.id, asset_type=kind).order_by(Candidate.name).all()
                if (any(row.validation_status != "VALIDATED" or row.issues or row.name != row.payload["name"] for row in rows)
                        or digest(sorted(expected, key=lambda item: item["name"])) != digest([row.payload for row in rows])):
                    issues.append("PARENT_PARSE_CANDIDATES_CHANGED")
            except (KeyError, TypeError, ValueError):
                issues.append("PARENT_PARSE_OUTPUT_INVALID")
    return parse_run, {row.id: row for row in rows}, issues


def _decision_receipt_issues(db, run, decision):
    issues = []
    if decision.llm_used:
        call = decision.call if isinstance(decision.call, dict) else None
        log = db.get(LLMLog, call.get("llmLogId")) if call and call.get("llmLogId") else None
        if (not call or call.get("status") != "VALIDATED" or not log or log.status != "success"
                or log.novel_id != run.novel_id or log.chapter_id != run.chapter_id
                or log.task_type != "asset_identity_resolution" or log.system_prompt != call.get("systemPrompt")
                or log.user_prompt != call.get("userPrompt") or log.response != call.get("response")
                or log.provider != call.get("provider") or log.model != call.get("model")
                or call.get("policyHash") != run.policy_hash or not call.get("templateHash")):
            issues.append("PARENT_RESOLVER_LOG_CHANGED")
        if not decision.manual_action:
            try:
                parsed = parse_resolution(call["response"], decision.asset_type)
                for key in ("resolution", "match_type", "confidence", "reason", "candidate_matches"):
                    if decision.plan.get(key) != parsed.get(key):
                        issues.append("PARENT_RESOLVER_PLAN_CHANGED")
                        break
                if (decision.resolution != decision.plan.get("resolution")
                        or decision.match_type != decision.plan.get("match_type")
                        or decision.confidence != decision.plan.get("confidence")
                        or decision.reason != decision.plan.get("reason") or decision.call != decision.plan.get("call")):
                    issues.append("PARENT_RESOLVER_DECISION_CHANGED")
            except (KeyError, TypeError, ValueError):
                issues.append("PARENT_RESOLVER_OUTPUT_INVALID")
    elif decision.call is not None:
        issues.append("PARENT_DETERMINISTIC_CALL_CHANGED")
    rules = decision.plan.get("rules_provenance") if isinstance(decision.plan, dict) else None
    if not isinstance(rules, dict) or not rules.get("version") or not rules.get("hash"):
        issues.append("PARENT_RULES_PROVENANCE_MISSING")
    return issues


def capture_parent_memberships(db, novel_id, chapter_id, kinds):
    result = {"version": OMISSION_VERSION, "kinds": {}}
    for kind in kinds:
        model, fk = BINDINGS[kind]
        rows = db.query(model).filter_by(novel_id=novel_id, chapter_id=chapter_id).order_by(model.id).all()
        snapshots = []
        run_ids = {row.resolution_run_id for row in rows}
        parent = db.get(Run, next(iter(run_ids))) if len(run_ids) == 1 else None
        global_issues = []
        if len(run_ids) > 1:
            global_issues.append("PARENT_BINDING_RUNS_MIXED")
        if rows and (not parent or parent.novel_id != novel_id or parent.chapter_id != chapter_id or kind not in parent.kinds):
            global_issues.append("PARENT_RESOLUTION_RUN_INVALID")
        decisions, carried, candidates, parse_run = [], [], {}, None
        if parent:
            task = db.get(Task, parent.task_id)
            if parent.status not in {"SUCCEEDED", "NEEDS_REVIEW"} or not task or task.status != "completed":
                global_issues.append("PARENT_RESOLUTION_RECEIPT_UNAVAILABLE")
            else:
                try:
                    metadata = json.loads(task.metadata_json or "{}")
                except (TypeError, ValueError):
                    metadata = {}
                if (task.type != TASK_TYPE or task.novel_id != novel_id or task.chapter_id != chapter_id
                        or metadata.get("resolution_run_id") != parent.id or metadata.get("resolver_version") != parent.resolver_version
                        or metadata.get("policy_hash") != parent.policy_hash or metadata.get("inputs") != parent.inputs):
                    global_issues.append("PARENT_RESOLUTION_TASK_CHANGED")
            if parent.input_hash != digest(parent.inputs):
                global_issues.append("PARENT_RESOLUTION_INPUT_CHANGED")
            decisions = db.query(Decision).filter_by(run_id=parent.id, asset_type=kind).all()
            if any(row.status not in {"APPLIED", "IGNORED"} for row in decisions):
                global_issues.append("PARENT_KIND_NOT_TERMINAL")
            for decision in decisions:
                if (decision.status == "APPLIED" and (not decision.asset_id or decision.resolution == "AMBIGUOUS")):
                    global_issues.append("PARENT_APPLIED_DECISION_INVALID")
                if (decision.status == "IGNORED" and (not isinstance(decision.manual_action, dict)
                        or decision.manual_action.get("action") != "IGNORE" or decision.asset_id is not None)):
                    global_issues.append("PARENT_IGNORED_DECISION_INVALID")
            carried = db.query(Omission).filter_by(run_id=parent.id, asset_type=kind, status="CARRIED").all()
            parse_run, candidates, parse_issues = _validated_parent_parse(db, parent, kind)
            global_issues.extend(parse_issues)
            if {row.candidate_id for row in decisions} != set(candidates):
                global_issues.append("PARENT_DECISION_SET_CHANGED")
            for decision in decisions:
                global_issues.extend(_decision_receipt_issues(db, parent, decision))
            expected_ids = {row.asset_id for row in decisions if row.status == "APPLIED"} | {row.asset_id for row in carried}
            if expected_ids != {getattr(row, fk) for row in rows}:
                global_issues.append("PARENT_BINDING_SET_CHANGED")
            if kind == "characters":
                expected_events = {(decision.candidate_id, proposal["event_key"]): (decision.asset_id, proposal)
                    for decision in decisions if decision.status == "APPLIED"
                    for proposal in decision.candidate.get("chapter_appearances", [])}
                events = db.query(AppearanceEvent).filter_by(chapter_id=chapter_id,
                    resolution_run_id=parent.id).order_by(AppearanceEvent.id).all()
                if {(row.candidate_id, row.event_key) for row in events} != set(expected_events):
                    global_issues.append("PARENT_APPEARANCE_EVENT_SET_CHANGED")
                else:
                    for event in events:
                        actor_id, proposal = expected_events[(event.candidate_id, event.event_key)]
                        if (event.character_id != actor_id or event.change_type != proposal["change_type"].upper()
                                or event.appearance_description != proposal["appearance_description"]
                                or event.source_evidence != proposal["source_evidence"]):
                            global_issues.append("PARENT_APPEARANCE_EVENT_CHANGED")
                            break
        for row in rows:
            asset_id = getattr(row, fk)
            snapshot = _binding_snapshot(row, fk)
            local_issues = list(global_issues)
            asset = db.get(MODELS[kind], asset_id)
            if row.status != "RESOLVED" or not asset or asset.novel_id != novel_id:
                local_issues.append("PARENT_BINDING_OR_ASSET_INVALID")
            if kind == "characters" and asset and (not asset.entity_type or asset.is_narrator):
                local_issues.append("PARENT_CHARACTER_IDENTITY_INVALID")
            members = [item for item in decisions if item.status == "APPLIED" and item.asset_id == asset_id]
            carry = next((item for item in carried if item.asset_id == asset_id), None)
            if members:
                for decision in members:
                    candidate = candidates.get(decision.candidate_id)
                    if not candidate or candidate.payload != decision.candidate:
                        local_issues.append("PARENT_DECISION_CANDIDATE_CHANGED")
                    elif any(quote["text"] not in (parse_run.source_content if parse_run else "")
                             for quote in decision.candidate.get("source_evidence", [])):
                        local_issues.append("PARENT_SOURCE_EVIDENCE_INVALID")
                    if kind == "characters" and asset and asset.entity_type != decision.candidate.get("entity_type"):
                        local_issues.append("PARENT_CHARACTER_TYPE_CHANGED")
                evidence = [quote for decision in members for quote in decision.candidate.get("source_evidence", [])]
                expected_evidence = list({quote["text"]: quote for quote in evidence}.values())
                if row.source_evidence != expected_evidence:
                    local_issues.append("PARENT_BINDING_EVIDENCE_CHANGED")
                expected_method = "MANUAL" if any(item.manual_action for item in members) else members[0].match_type
                roles = [item.candidate.get("chapter_presence", {}).get("role") for item in members]
                expected_role = next((role for role in ("MAJOR", "SUPPORTING", "BACKGROUND") if role in roles), None)
                if (row.resolution_method != expected_method or row.resolution_confidence != min(item.confidence for item in members)
                        or row.chapter_role != expected_role):
                    local_issues.append("PARENT_BINDING_PROJECTION_CHANGED")
                provenance_ids = {item.get("decision_id") for item in row.provenance if isinstance(item, dict) and item.get("decision_id")}
                if provenance_ids != {item.id for item in members}:
                    local_issues.append("PARENT_BINDING_PROVENANCE_CHANGED")
            elif carry:
                if carry.proof_hash != digest(carry.proof):
                    local_issues.append("PARENT_CARRY_PROOF_CHANGED")
                carry_links = [item for item in row.provenance if isinstance(item, dict)
                    and item.get("omission_id") == carry.id and item.get("proof_hash") == carry.proof_hash]
                prior = carry.proof.get("parent_binding", {})
                identity = carry.proof.get("asset_identity", {})
                if (not carry_links or row.resolution_method != "SOURCE_EVIDENCE_CARRY_FORWARD"
                        or carry.prior_binding_id != row.id or row.chapter_role != prior.get("chapter_role")
                        or row.resolution_confidence != prior.get("resolution_confidence")
                        or row.source_evidence != prior.get("source_evidence")):
                    local_issues.append("PARENT_CARRY_BINDING_CHANGED")
                if kind == "characters" and asset and asset.entity_type != identity.get("entity_type"):
                    local_issues.append("PARENT_CARRY_CHARACTER_TYPE_CHANGED")
            else:
                local_issues.append("PARENT_BINDING_HAS_NO_AUTHORITY")
            appearance_count = (db.query(AppearanceEvent.id).filter_by(chapter_id=chapter_id,
                character_id=asset_id).count() if kind == "characters" else 0)
            snapshots.append({"binding": snapshot, "asset_id": asset_id,
                "source_hash": parent.inputs.get("source_hash") if parent and isinstance(parent.inputs, dict) else None,
                "provenance_valid": not local_issues, "provenance_issues": sorted(set(local_issues)),
                "appearance_event_count": appearance_count})
        value = {"parent_resolution_run_id": parent.id if parent else None, "bindings": snapshots,
                 "provenance_valid": not global_issues and all(item["provenance_valid"] for item in snapshots),
                 "provenance_issues": sorted(set(global_issues))}
        value["hash"] = digest(value)
        result["kinds"][kind] = value
    result["hash"] = digest(result)
    return result


def _resolution_kind_receipt_valid(db, run, kind):
    task = db.get(Task, run.task_id)
    if not task or task.status != "completed" or task.type != TASK_TYPE or task.novel_id != run.novel_id or task.chapter_id != run.chapter_id:
        return False
    try:
        metadata = json.loads(task.metadata_json or "{}")
    except (TypeError, ValueError):
        return False
    if (run.input_hash != digest(run.inputs) or metadata.get("resolution_run_id") != run.id
            or metadata.get("resolver_version") != run.resolver_version or metadata.get("policy_hash") != run.policy_hash
            or metadata.get("inputs") != run.inputs):
        return False
    parse_run, candidates, issues = _validated_parent_parse(db, run, kind)
    decisions = db.query(Decision).filter_by(run_id=run.id, asset_type=kind).all()
    if issues or {row.candidate_id for row in decisions} != set(candidates):
        return False
    for decision in decisions:
        if decision.status not in {"APPLIED", "IGNORED"} or _decision_receipt_issues(db, run, decision):
            return False
        if decision.candidate != candidates[decision.candidate_id].payload:
            return False
        if decision.status == "APPLIED" and (not decision.asset_id or decision.resolution == "AMBIGUOUS"):
            return False
        if (decision.status == "IGNORED" and (not isinstance(decision.manual_action, dict)
                or decision.manual_action.get("action") != "IGNORE" or decision.asset_id is not None)):
            return False
    return True


def _published_kind_valid(db, run, kind):
    expected = ({row.asset_id for row in db.query(Decision).filter_by(
        run_id=run.id, asset_type=kind, status="APPLIED")} | _carried_ids(db, run.id, kind))
    model, fk = BINDINGS[kind]
    rows = db.query(model).filter_by(novel_id=run.novel_id, chapter_id=run.chapter_id).all()
    if expected != {getattr(row, fk) for row in rows}:
        return False
    carried = db.query(Omission).filter_by(run_id=run.id, asset_type=kind, status="CARRIED").all()
    if not _resolution_kind_receipt_valid(db, run, kind) or any(row.proof_hash != digest(row.proof) for row in carried):
        return False
    if not expected:
        return not rows
    receipt = capture_parent_memberships(db, run.novel_id, run.chapter_id, [kind])["kinds"][kind]
    membership_issues = [issue for issue in receipt.get("provenance_issues", []) if issue not in EVENT_PROVENANCE_ISSUES]
    binding_issues = [issue for item in receipt.get("bindings", []) for issue in item.get("provenance_issues", [])
                      if issue not in EVENT_PROVENANCE_ISSUES]
    return receipt["parent_resolution_run_id"] == run.id and not membership_issues and not binding_issues


def acquire(db, novel_id, owner, timeout):
    db.query(Lease).filter(Lease.novel_id == novel_id, Lease.expires_at < datetime.utcnow()).delete(synchronize_session=False)
    db.add(Lease(novel_id=novel_id, owner=owner, expires_at=datetime.utcnow() + timedelta(seconds=timeout)))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "本小说正在归并或处理身份，请稍后再试")


def fence(db, novel_id, owner, timeout=120):
    count = db.query(Lease).filter(Lease.novel_id == novel_id, Lease.owner == owner,
                                  Lease.expires_at >= datetime.utcnow()).update({
        "expires_at": datetime.utcnow() + timedelta(seconds=timeout)}, synchronize_session=False)
    if count != 1:
        db.rollback()
        raise ResolutionFailure("RESOLUTION_LEASE_LOST")


def release(db, novel_id, owner):
    db.rollback()
    db.query(Lease).filter_by(novel_id=novel_id, owner=owner).delete(synchronize_session=False)
    db.commit()


def fail_resolution(db, run_id, message):
    db.rollback()
    run = db.get(Run, run_id)
    if not run:
        return False
    task_id = run.task_id
    changed = db.query(Run).filter_by(id=run_id, status="RUNNING").update({
        "status": "FAILED", "issues": [{"code": "RESOLUTION_FAILED", "message": message}], "completed_at": datetime.utcnow(),
    }, synchronize_session=False)
    if changed:
        db.query(Task).filter(Task.id == task_id, Task.status.in_(["pending", "running"])).update({
            "status": "failed", "current_step": "身份归并失败", "error_message": message, "completed_at": datetime.utcnow(),
        }, synchronize_session=False)
        db.commit()
    db.expire_all()
    return bool(changed)


def expire_resolution_task(db, task):
    run = db.query(Run).filter_by(task_id=task.id, status="RUNNING").first()
    if run and run.expires_at < datetime.utcnow():
        return fail_resolution(db, run.id, "RESOLUTION_EXPIRED: 请从章回新建执行")
    return False


def run_is_current(db, run, kinds=None):
    try:
        kinds = kinds or run.kinds
        _, inputs, _ = current_inputs(db, run.novel_id, run.chapter_id, kinds)
        return (run.resolver_version == VERSION and run.policy_hash == load_policy()["hash"]
                and run.input_hash == digest(run.inputs)
                and all(inputs["kinds"][kind] == run.inputs["kinds"][kind] for kind in kinds))
    except (HTTPException, ValueError, KeyError, OSError):
        return False


def decision_response(row):
    return {"id": row.id, "candidateId": row.candidate_id, "assetType": row.asset_type, "candidate": row.candidate,
            "resolution": row.resolution, "matchType": row.match_type, "confidence": row.confidence,
            "reason": row.reason, "llmUsed": row.llm_used, "status": row.status, "assetId": row.asset_id,
            "canonicalName": row.plan.get("canonical_name"), "shortlist": row.shortlist,
            "candidateMatches": row.plan.get("candidate_matches", []),
            "call": row.call, "manualAction": row.manual_action}


def resolution_response(db, run):
    current = run_is_current(db, run)
    newer = db.query(Run).filter(Run.chapter_id == run.chapter_id).filter(
        (Run.created_at > run.created_at) | ((Run.created_at == run.created_at) & (Run.id > run.id))).all()
    superseded = any(set(other.kinds) & set(run.kinds) for other in newer)
    status = "STALE" if not current else "SUPERSEDED" if superseded else run.status
    rows = db.query(Decision).filter_by(run_id=run.id).order_by(Decision.asset_type, Decision.id).all()
    omissions = db.query(Omission).filter_by(run_id=run.id).order_by(Omission.asset_type, Omission.id).all()
    pending_kinds = {kind for kind in run.kinds if _pending_kind(db, run.id, kind)}
    if status == "SUCCEEDED" and pending_kinds:
        status = "STALE"
    task = db.get(Task, run.task_id)
    if status in {"SUCCEEDED", "NEEDS_REVIEW"}:
        for decision in rows:
            if decision.status != "APPLIED" or decision.asset_type in pending_kinds:
                continue
            asset = db.get(MODELS[decision.asset_type], decision.asset_id)
            binding_model, fk = BINDINGS[decision.asset_type]
            bound = db.query(binding_model.id).filter_by(chapter_id=run.chapter_id,
                resolution_run_id=run.id, status="RESOLVED", **{fk: decision.asset_id}).first()
            if (not asset or asset.novel_id != run.novel_id or not bound
                    or (decision.asset_type == "characters" and (asset.entity_type != decision.candidate["entity_type"] or asset.is_narrator))):
                status = "STALE"
        for omission in omissions:
            if omission.status != "CARRIED" or omission.asset_type in pending_kinds:
                continue
            asset = db.get(MODELS[omission.asset_type], omission.asset_id)
            binding_model, fk = BINDINGS[omission.asset_type]
            bound = db.query(binding_model).filter_by(chapter_id=run.chapter_id,
                resolution_run_id=run.id, status="RESOLVED", **{fk: omission.asset_id}).first()
            carry_link = bool(bound and any(isinstance(item, dict) and item.get("omission_id") == omission.id
                and item.get("proof_hash") == omission.proof_hash for item in bound.provenance))
            if (not asset or asset.novel_id != run.novel_id or not bound or not carry_link
                    or bound.resolution_method != "SOURCE_EVIDENCE_CARRY_FORWARD"
                    or omission.proof_hash != digest(omission.proof)):
                status = "STALE"
        if any(kind not in pending_kinds and not _published_kind_valid(db, run, kind) for kind in run.kinds):
            status = "STALE"
        if not task or task.status != "completed":
            status = "STALE"
    active_review_kinds = {kind for kind in run.kinds if status == "NEEDS_REVIEW" and run_is_current(db, run, [kind])
                            and not any(kind in other.kinds for other in newer)}
    return {"id": run.id, "novelId": run.novel_id, "chapterId": run.chapter_id, "taskId": run.task_id,
             "status": run.status, "effectiveStatus": status, "resolverVersion": run.resolver_version,
             "policyHash": run.policy_hash, "inputs": run.inputs, "kinds": run.kinds, "issues": run.issues,
             "phase2Ready": status == "SUCCEEDED", "decisions": [decision_response(row) for row in rows],
             "omissions": [omission_response(row) for row in omissions],
             "reviews": [decision_response(row) for row in rows if row.status == "PENDING_REVIEW" and row.asset_type in active_review_kinds]
                       if run.status == "NEEDS_REVIEW" else [],
            "createdAt": run.created_at.isoformat() + "Z"}


def binding_state(db, novel_id, chapter_id):
    if not db.query(Chapter.id).filter_by(id=chapter_id, novel_id=novel_id).first():
        raise HTTPException(404, "章回不存在")
    runs = db.query(Run).filter_by(novel_id=novel_id, chapter_id=chapter_id).order_by(Run.created_at.desc(), Run.id.desc()).all()
    result = {}
    for kind, (model, fk) in BINDINGS.items():
        run = next((row for row in runs if kind in row.kinds), None)
        current = bool(run and run_is_current(db, run, [kind]))
        status = "NOT_RESOLVED" if not run else "STALE" if not current else run.status
        task = db.get(Task, run.task_id) if run else None
        if current and (not task or task.status != "completed"):
            status = "STALE"
        pending = bool(run and _pending_kind(db, run.id, kind))
        if status == "SUCCEEDED" and pending:
            status = "STALE"
        if status == "NEEDS_REVIEW" and not pending:
            status = "SUCCEEDED"
        rows = db.query(model).filter_by(chapter_id=chapter_id, novel_id=novel_id).all()
        carry_rows = {row.asset_id: row for row in db.query(Omission).filter_by(
            run_id=run.id, asset_type=kind, status="CARRIED").all()} if run else {}
        bindings = []
        for row in rows:
            if not current or row.resolution_run_id != run.id or row.status != "RESOLVED" or status not in {"SUCCEEDED", "NEEDS_REVIEW"}:
                continue
            asset = db.get(MODELS[kind], getattr(row, fk))
            if not asset or asset.novel_id != novel_id:
                status = "STALE"
                continue
            if kind == "characters" and (not asset.entity_type or asset.is_narrator):
                status = "STALE"
                continue
            carry = carry_rows.get(asset.id)
            if carry and (carry.proof_hash != digest(carry.proof) or row.resolution_method != "SOURCE_EVIDENCE_CARRY_FORWARD"
                    or not any(isinstance(item, dict) and item.get("omission_id") == carry.id
                               and item.get("proof_hash") == carry.proof_hash for item in row.provenance)):
                status = "STALE"
                continue
            bindings.append({"id": row.id, "assetId": asset.id, "name": asset.name, "chapterRole": row.chapter_role,
                "entityType": asset.entity_type if kind == "characters" else None,
                "method": row.resolution_method, "confidence": row.resolution_confidence,
                "sourceEvidence": row.source_evidence,
                "provenance": row.provenance, "resolutionRunId": row.resolution_run_id})
        if current and status in {"SUCCEEDED", "NEEDS_REVIEW"} and not pending:
            expected = ({row.asset_id for row in db.query(Decision).filter_by(run_id=run.id, asset_type=kind, status="APPLIED")}
                        | _carried_ids(db, run.id, kind))
            if expected != {row["assetId"] for row in bindings}:
                status = "STALE"
            elif not _published_kind_valid(db, run, kind):
                status = "STALE"
        result[kind] = {"status": status, "runId": run.id if run else None, "bindings": bindings,
                        "emptyConfirmed": bool(current and status == "SUCCEEDED" and not bindings)}
    return {"phase2Ready": all(item["status"] == "SUCCEEDED" for item in result.values()), "assets": result}


class AssetResolutionService:
    def __init__(self, db, llm=None):
        self.db, self.llm = db, llm

    async def plan(self, kind, payload, assets, policy, chapter, candidates, on_call=None):
        excerpt = context_excerpt(chapter.content or "", payload["source_evidence"])
        method, target = deterministic(kind, payload, assets[kind], policy, excerpt, assets["characters"])
        shortlist = retrieve(kind, payload, [row for row in assets[kind] if not row.get("provisional")], excerpt, policy["rules"]["top_k"])
        if target:
            return {"resolution": "EXISTING", "match_type": method, "matched_asset_id": target["asset_id"],
                    "canonical_name": target["canonical_name"], "confidence": 1.0, "needs_review": False,
                    "candidate_matches": [], "reason": method, "llm_used": False, "shortlist": [target], "call": None}
        exact_conflicts = [row for row in shortlist if row["canonical_name"] == payload["name"]]
        if exact_conflicts and (len(exact_conflicts) > 1 or any(not compatible(kind, payload, row) for row in exact_conflicts)):
            return {"resolution": "AMBIGUOUS", "match_type": "AMBIGUOUS", "matched_asset_id": None,
                    "canonical_name": payload["name"], "confidence": 0.0, "needs_review": True,
                    "candidate_matches": [{"asset_id": row["asset_id"], "canonical_name": row["canonical_name"], "confidence": 0.0} for row in exact_conflicts],
                    "reason": "同名多记录或既有类型未确认/冲突，需要人工选择", "llm_used": False, "shortlist": shortlist, "call": None}
        if not shortlist:
            return {"resolution": "NEW", "match_type": "NEW", "matched_asset_id": None, "canonical_name": payload["name"],
                    "confidence": 1.0, "needs_review": False, "candidate_matches": [], "reason": "EMPTY_BOOK_CATALOG",
                    "llm_used": False, "shortlist": [], "call": None}
        llm = self.llm or LLMService()
        key = "candidate_character" if kind == "characters" else "candidate_asset"
        body = {key: payload, "asset_type": kind, "existing_candidates": shortlist,
                "chapter": {"id": chapter.id, "title": chapter.title, "context": excerpt}}
        system_prompt = policy["prompts"]["character_prompt" if kind == "characters" else "asset_prompt"]
        user_prompt = policy["prompts"]["user_template"].format_map({"payload": json.dumps(body, ensure_ascii=False)})
        call = {"templateVersion": policy["prompts"]["version"], "templateHash": policy["prompt_hash"],
                "policyHash": policy["hash"], "systemPrompt": system_prompt, "userPrompt": user_prompt,
                "provider": llm.provider, "model": llm.model, "llmLogId": None, "response": None, "status": "RUNNING"}
        if on_call:
            on_call(call)
        response = await asyncio.wait_for(llm.chat_completion(system_prompt=system_prompt, user_content=user_prompt,
            response_format="json_object", temperature=0.1, max_tokens=4096, task_type="asset_identity_resolution",
            prompt_template_name=policy["prompts"]["version"], novel_id=chapter.novel_id, chapter_id=chapter.id),
            timeout=float(getattr(llm, "timeout", None) or 1800) + 5)
        call.update(llmLogId=response.get("llm_log_id"), response=response.get("content"),
                    status="RETURNED" if response.get("success") else "FAILED")
        if on_call:
            on_call(call)
        if not response.get("success"):
            raise ResolutionFailure(response.get("error") or "RESOLVER_LLM_FAILED")
        log = self.db.get(LLMLog, call["llmLogId"]) if call["llmLogId"] else None
        if (not log or log.status != "success" or log.novel_id != chapter.novel_id or log.chapter_id != chapter.id
                or log.system_prompt != system_prompt or log.user_prompt != user_prompt or log.response != call["response"]):
            raise ResolutionFailure("RESOLVER_LOG_UNVERIFIED")
        output = parse_resolution(call["response"], kind)
        by_id = {item["asset_id"]: item for item in shortlist}
        for match in output["candidate_matches"]:
            if match["asset_id"] not in by_id or match["canonical_name"] != by_id[match["asset_id"]]["canonical_name"]:
                raise ResolutionFailure("INVALID_SHORTLIST_ID")
        if output["resolution"] == "EXISTING":
            target = by_id.get(output["matched_asset_id"])
            if not target or not compatible(kind, payload, target) or output["canonical_name"] != target["canonical_name"]:
                raise ResolutionFailure("INVALID_EXISTING_ID_OR_TYPE")
            if output["match_type"] == "STRONG_ALIAS" and payload["name"] not in target["strong_aliases"]:
                raise ResolutionFailure("UNVERIFIED_STRONG_ALIAS")
            if output["match_type"] == "EXACT_NAME" and payload["name"] != target["canonical_name"]:
                raise ResolutionFailure("EXACT_NAME_NOT_EXACT")
        elif output["resolution"] == "NEW":
            if kind == "characters" and payload["entity_type"] == "INDIVIDUAL" and output["canonical_name"] != payload["name"]:
                raise ResolutionFailure("NEW_INDIVIDUAL_RENAMED: " + json.dumps({
                    "candidate_name": payload["name"], "canonical_name": output["canonical_name"]}, ensure_ascii=False))
        call["status"] = "VALIDATED"
        return {**output, "llm_used": True, "shortlist": shortlist, "call": call}

    def _assert_parent_baseline(self, run, kinds):
        actual = capture_parent_memberships(self.db, run.novel_id, run.chapter_id, kinds)
        expected = run.inputs.get("parent_memberships", {}).get("kinds", {})
        if any(kind not in expected or actual["kinds"][kind]["hash"] != expected[kind]["hash"] for kind in kinds):
            raise ResolutionFailure("BINDING_BASELINE_CHANGED")

    def _lock_publication_scope(self, run, kinds):
        db = self.db
        chapter = db.query(Chapter).filter_by(id=run.chapter_id, novel_id=run.novel_id).with_for_update().populate_existing().first()
        task = db.query(Task).filter_by(id=run.task_id).with_for_update().populate_existing().first()
        db.query(Run).filter_by(id=run.id).with_for_update().populate_existing().first()
        for kind in kinds:
            model, _ = BINDINGS[kind]
            db.query(model).filter_by(chapter_id=run.chapter_id, novel_id=run.novel_id).with_for_update().all()
        if not chapter or not task:
            raise ResolutionFailure("RESOLUTION_PUBLICATION_SCOPE_MISSING")
        return chapter, task

    def _omission_conflicts(self, run, kind, parent, decisions):
        db = self.db
        asset = db.get(MODELS[kind], parent["asset_id"])
        names = {asset.name} if asset else set()
        if kind == "characters" and asset:
            names.update(row.alias for row in db.query(CharacterAlias).filter_by(character_id=asset.id))
        old_evidence = parent["binding"].get("source_evidence") or []
        old_group = kind == "characters" and asset and asset.entity_type == "GROUP"
        parent_ids = {item["asset_id"] for item in run.inputs.get("parent_memberships", {}).get(
            "kinds", {}).get(kind, {}).get("bindings", [])}
        content = db.get(Chapter, run.chapter_id).content or ""
        conflicts = []
        for decision in decisions:
            if decision.asset_type != kind or decision.status != "APPLIED" or decision.asset_id == parent["asset_id"]:
                continue
            candidate_name = decision.candidate.get("name")
            candidate_matches = decision.plan.get("candidate_matches", []) if isinstance(decision.plan, dict) else []
            overlap = _overlapping_evidence(content, old_evidence, decision.candidate.get("source_evidence", []))
            if candidate_name in names:
                conflicts.append({"code": "CANONICAL_OR_ALIAS_REASSIGNED", "decision_id": decision.id})
            if any(item.get("asset_id") == parent["asset_id"] for item in candidate_matches):
                conflicts.append({"code": "OLD_ASSET_WAS_ALTERNATIVE_MATCH", "decision_id": decision.id})
            if old_group and decision.asset_id not in parent_ids:
                conflicts.append({"code": "GROUP_TOPOLOGY_CHANGED", "decision_id": decision.id})
            if overlap:
                conflicts.append({"code": "SOURCE_EVIDENCE_OVERLAP", "decision_id": decision.id})
        return conflicts

    def _classify_omissions(self, run, decisions, kind):
        db = self.db
        existing = db.query(Omission).filter_by(run_id=run.id, asset_type=kind).order_by(Omission.id).all()
        if existing:
            return existing
        parent = run.inputs.get("parent_memberships", {}).get("kinds", {}).get(kind, {})
        applied_ids = {row.asset_id for row in decisions if row.asset_type == kind and row.status == "APPLIED"}
        created = []
        for item in parent.get("bindings", []):
            if item["asset_id"] in applied_ids:
                continue
            conflicts = self._omission_conflicts(run, kind, item, decisions)
            same_source = item.get("source_hash") == run.inputs.get("source_hash")
            if not item.get("provenance_valid"):
                status, reason = "PENDING_REVIEW", "PARENT_PROVENANCE_INCOMPLETE"
            elif not same_source:
                status, reason = "PENDING_REVIEW", "SOURCE_HASH_CHANGED"
            elif item.get("appearance_event_count"):
                status, reason = "PENDING_REVIEW", "APPEARANCE_EVENT_LINEAGE_UNSUPPORTED"
            elif conflicts:
                status, reason = "PENDING_REVIEW", "IDENTITY_TOPOLOGY_CONFLICT"
            else:
                status, reason = "CARRIED", "IDENTICAL_SOURCE_AUTHORITATIVE_PARENT"
            asset = db.get(MODELS[kind], item["asset_id"])
            proof = {"version": OMISSION_VERSION, "parent_membership_hash": parent.get("hash"),
                "parent_binding": deepcopy(item["binding"]), "parent_provenance_valid": item.get("provenance_valid"),
                "parent_provenance_issues": deepcopy(item.get("provenance_issues") or []),
                "parent_source_hash": item.get("source_hash"), "current_source_hash": run.inputs.get("source_hash"),
                "same_source": same_source, "appearance_event_count": item.get("appearance_event_count", 0),
                "identity_conflicts": conflicts, "current_resolution_input_hash": run.input_hash,
                "asset_identity": {"name": asset.name if asset else None,
                    "entity_type": asset.entity_type if kind == "characters" and asset else None}}
            row = Omission(id=str(uuid4()), run_id=run.id, asset_type=kind, asset_id=item["asset_id"],
                prior_binding_id=item["binding"]["id"],
                prior_resolution_run_id=item["binding"]["resolution_run_id"], status=status,
                reason_code=reason, proof=proof, proof_hash=digest(proof))
            db.add(row)
            created.append(row)
        db.flush()
        return created

    def _reconcile_kind(self, run, decisions, kind):
        if any(row.asset_type == kind and row.status not in {"APPLIED", "IGNORED"} for row in decisions):
            return False
        omissions = self._classify_omissions(run, decisions, kind)
        if any(row.status == "PENDING_REVIEW" for row in omissions):
            return False
        self._sync_bindings(run, decisions, [kind], omissions)
        return True

    def _pending_issues(self, run, decisions):
        issues = []
        for decision in decisions:
            if decision.status not in {"APPLIED", "IGNORED"}:
                issues.append({"code": "IDENTITY_REVIEW_REQUIRED" if decision.status == "PENDING_REVIEW"
                               else "IDENTITY_DECISION_NOT_TERMINAL", "assetType": decision.asset_type,
                               "decisionId": decision.id, "status": decision.status})
        for omission in self.db.query(Omission).filter_by(run_id=run.id, status="PENDING_REVIEW").order_by(Omission.asset_type, Omission.id):
            issues.append({"code": "ASSET_OMISSION_REVIEW_REQUIRED", "assetType": omission.asset_type,
                           "assetId": omission.asset_id, "omissionId": omission.id, "reasonCode": omission.reason_code})
        return issues

    async def resolve(self, novel_id, chapter_id, kinds=None, force=False):
        kinds = ResolveRequest(kinds=kinds if kinds is not None else list(MODELS), force=force).kinds
        db = self.db
        from app.services.rebuild_context import stage_parent
        parent_task_id = stage_parent(db, chapter_id)
        chapter, inputs, candidates = current_inputs(db, novel_id, chapter_id, kinds)
        policy = load_policy()
        old = db.query(Run).filter_by(novel_id=novel_id, chapter_id=chapter_id).order_by(Run.created_at.desc(), Run.id.desc()).first()
        if (old and not force and old.policy_hash == policy["hash"] and old.status in {"SUCCEEDED", "NEEDS_REVIEW"}
                and _parse_inputs_equal(old.inputs, inputs, kinds)):
            data = resolution_response(db, old)
            if data["effectiveStatus"] in {"SUCCEEDED", "NEEDS_REVIEW"}:
                return {"success": data["phase2Ready"], "data": data, "reused": True}
        run_id, task_id = str(uuid4()), str(uuid4())
        timeout = float(getattr(self.llm, "timeout", None) or getattr(LLMService(), "timeout", None) or 1800) + 60
        acquire(db, novel_id, run_id, timeout)
        run_created = False
        try:
            db.expire_all()
            chapter, inputs, candidates = current_inputs(db, novel_id, chapter_id, kinds)
            inputs = {**inputs, "parent_memberships": capture_parent_memberships(db, novel_id, chapter_id, kinds)}
            assets, catalog_hash = catalog(db, novel_id)
            run = Run(id=run_id, novel_id=novel_id, chapter_id=chapter_id, task_id=task_id,
                resolver_version=VERSION, policy_hash=policy["hash"], kinds=kinds, inputs=inputs, input_hash=digest(inputs),
                catalog_hash=catalog_hash, status="RUNNING", expires_at=datetime.utcnow() + timedelta(seconds=timeout))
            task = Task(id=task_id, novel_id=novel_id, chapter_id=chapter_id, type=TASK_TYPE, status="running", parent_task_id=parent_task_id,
                name=f"章回身份归并 · 第{chapter.number}回", started_at=datetime.utcnow(), current_step="身份归并准备",
                metadata_json=json.dumps({"execution_purpose": "production", "resolution_run_id": run_id,
                    "resolver_version": VERSION, "policy_hash": policy["hash"], "inputs": inputs}, ensure_ascii=False))
            db.add_all([run, task])
            db.commit()
            run_created = True
            planned = []
            for candidate in candidates:
                payload, kind = deepcopy(candidate.payload), candidate.asset_type
                decision = Decision(id=str(uuid4()), run_id=run_id, candidate_id=candidate.id, asset_type=kind,
                    candidate=payload, resolution="AMBIGUOUS", match_type="AMBIGUOUS", confidence=0,
                    reason="PLANNING", llm_used=False, shortlist=[], plan={}, status="PLANNED")
                db.add(decision)
                db.commit()
                decision_id = decision.id
                def save_call(call):
                    fence(db, novel_id, run_id, timeout)
                    db.query(Decision).filter_by(id=decision_id).update({"call": deepcopy(call), "llm_used": True}, synchronize_session=False)
                    db.query(Run).filter_by(id=run_id, status="RUNNING").update({"expires_at": datetime.utcnow() + timedelta(seconds=timeout)}, synchronize_session=False)
                    db.commit()
                started = perf_counter()
                plan = await self.plan(kind, payload, assets, policy, chapter, candidates, save_call)
                linked_log = db.get(LLMLog, plan['call'].get('llmLogId')) if plan.get('call') and plan['call'].get('llmLogId') else None
                plan['metrics'] = {'latency_ms': round((perf_counter()-started)*1000,3),
                    'token_usage': deepcopy(linked_log.usage_metrics) if linked_log else None,
                    'llm_log_id': linked_log.id if linked_log else None,
                    'measurement': 'PERF_COUNTER_ELAPSED', 'token_usage_source': 'LLM_LOG' if linked_log else 'NO_LLM_CALL'}
                if plan["resolution"] == "NEW":
                    name = plan["canonical_name"].strip()
                    if not name or any(item["canonical_name"] == name for item in assets[kind]):
                        raise ResolutionFailure("NEW_NAME_COLLISION")
                    plan.update(canonical_name=name, proposed_id=str(uuid4()))
                    assets[kind].append({"asset_id": plan["proposed_id"], "canonical_name": name,
                        "entity_type": payload.get("entity_type"), "description": payload["description"],
                        "context": {}, "strong_aliases": policy["rules"]["strong_aliases"].get(name, []) if kind == "characters" else [],
                        "contextual_aliases": [], "provisional": True})
                plan["rules_provenance"] = {"version": policy["rules"]["version"], "hash": policy["rules_hash"]}
                db.query(Decision).filter_by(id=decision_id).update({"resolution": plan["resolution"], "match_type": plan["match_type"],
                    "confidence": plan["confidence"], "reason": plan["reason"], "llm_used": plan["llm_used"],
                    "shortlist": plan["shortlist"], "call": plan["call"], "plan": plan}, synchronize_session=False)
                db.commit()
                planned.append(decision_id)
            # One write transaction validates current inputs/catalog and publishes all non-ambiguous decisions.
            db.expire_all()
            fence(db, novel_id, run_id)
            stage_parent(db, chapter_id)
            run = db.get(Run, run_id)
            chapter, task = self._lock_publication_scope(run, kinds)
            _, actual_inputs, _ = current_inputs(db, novel_id, chapter_id, kinds)
            if (not _parse_inputs_equal(inputs, actual_inputs, kinds) or load_policy()["hash"] != policy["hash"]
                    or catalog(db, novel_id)[1] != catalog_hash):
                raise ResolutionFailure("SOURCE_OR_CATALOG_CHANGED")
            if not task or task.status != "running" or run.status != "RUNNING":
                raise ResolutionFailure("RESOLUTION_TASK_CHANGED")
            self._assert_parent_baseline(run, kinds)
            decisions = [db.get(Decision, item) for item in planned]
            for decision in decisions:
                if decision.resolution == "AMBIGUOUS":
                    decision.status = "PENDING_REVIEW"
                else:
                    self._apply(decision, run, policy, chapter)
            for kind in kinds:
                self._reconcile_kind(run, decisions, kind)
            pending = any(_pending_kind(db, run.id, kind) for kind in kinds)
            run.status = "NEEDS_REVIEW" if pending else "SUCCEEDED"
            run.issues = self._pending_issues(run, decisions)
            run.completed_at = datetime.utcnow()
            task.status, task.progress, task.completed_at = "completed", 100, datetime.utcnow()
            task.current_step = "存在歧义或资产遗漏，等待检查" if pending else "章回身份归并完成"
            db.flush()
            _, final_inputs, _ = current_inputs(db, novel_id, chapter_id, kinds)
            if not _parse_inputs_equal(inputs, final_inputs, kinds):
                raise ResolutionFailure("SOURCE_CHANGED_DURING_PUBLICATION")
            db.commit()
        except asyncio.CancelledError:
            if run_created:
                fail_resolution(db, run_id, "RESOLUTION_INTERRUPTED")
            raise
        except Exception as exc:
            if not run_created:
                raise
            fail_resolution(db, run_id, str(exc))
        finally:
            release(db, novel_id, run_id)
        db.expire_all()
        data = resolution_response(db, db.get(Run, run_id))
        return {"success": data["phase2Ready"], "data": data}

    def _apply(self, decision, run, policy, chapter, *, create_name=None, target_id=None, confirm_type=False):
        db, kind, payload = self.db, decision.asset_type, decision.candidate
        plan = decision.plan
        creating = create_name is not None or decision.resolution == "NEW"
        if creating:
            name = (create_name or plan["canonical_name"]).strip()
            if not name or db.query(MODELS[kind].id).filter_by(novel_id=run.novel_id, name=name).first():
                raise HTTPException(409, "规范名已存在或无效，请匹配已有资产")
            values = {"id": plan.get("proposed_id") or str(uuid4()), "novel_id": run.novel_id, "name": name,
                      "description": payload["description"]}
            values["setting" if kind == "scenes" else "appearance"] = payload["setting" if kind == "scenes" else "appearance"]
            if kind == "characters":
                values["voice_prompt"] = payload.get("voice_prompt") or ""
            asset = MODELS[kind](**values)
            db.add(asset)
            db.flush()
        else:
            asset = db.get(MODELS[kind], target_id or plan["matched_asset_id"])
            if not asset or asset.novel_id != run.novel_id:
                raise HTTPException(409, "目标资产不存在或不属于此小说")
        if kind == "characters":
            if asset.is_narrator:
                raise HTTPException(409, "旁白不能匹配为可视角色候选")
            identity = db.get(CharacterIdentity, asset.id)
            if not identity:
                if not creating and not confirm_type:
                    raise HTTPException(409, "旧角色类型未确认，请显式确认本次角色类型")
                db.add(CharacterIdentity(character_id=asset.id, novel_id=run.novel_id, entity_type=payload["entity_type"],
                    group_size_hint=payload["group_size_hint"], context={"description": payload["description"],
                        "source_evidence": payload["source_evidence"], "chapter_context": context_excerpt(chapter.content or "", payload["source_evidence"])},
                    provenance={"decision_id": decision.id, "candidate_id": decision.candidate_id,
                                "origin": "NEW" if creating else "MANUAL_TYPE_CONFIRMATION"}))
                seed_aliases(db, asset, policy, {"decision_id": decision.id, "rules_hash": policy["rules_hash"]})
            elif identity.entity_type != payload["entity_type"]:
                raise HTTPException(409, "角色类型冲突")
        decision.asset_id, decision.status = asset.id, "APPLIED"
        decision.plan = {**plan, "canonical_name": asset.name}
        db.flush()

    def _sync_bindings(self, run, decisions, kinds=None, omissions=None):
        db = self.db
        for kind in kinds or run.kinds:
            model, fk = BINDINGS[kind]
            groups = {}
            for decision in decisions:
                if decision.asset_type == kind and decision.status == "APPLIED":
                    groups.setdefault(decision.asset_id, []).append(decision)
            carries = {row.asset_id: row for row in (omissions or db.query(Omission).filter_by(
                run_id=run.id, asset_type=kind, status="CARRIED").all()) if row.asset_type == kind and row.status == "CARRIED"}
            expected_ids = set(groups) | set(carries)
            for old in db.query(model).filter_by(chapter_id=run.chapter_id).all():
                if getattr(old, fk) not in expected_ids:
                    db.delete(old)
            for asset_id, members in groups.items():
                row = db.query(model).filter_by(chapter_id=run.chapter_id, **{fk: asset_id}).first()
                if not row:
                    row = model(novel_id=run.novel_id, chapter_id=run.chapter_id, **{fk: asset_id})
                    db.add(row)
                evidence = [quote for decision in members for quote in decision.candidate["source_evidence"]]
                row.source_evidence = list({quote["text"]: quote for quote in evidence}.values())
                row.status, row.resolution_run_id = "RESOLVED", run.id
                row.resolution_method = "MANUAL" if any(d.manual_action for d in members) else members[0].match_type
                row.resolution_confidence = min(d.confidence for d in members)
                roles = [d.candidate.get("chapter_presence", {}).get("role") for d in members]
                row.chapter_role = next((role for role in ("MAJOR", "SUPPORTING", "BACKGROUND") if role in roles), None)
                row.provenance = [{"decision_id": d.id, "candidate_id": d.candidate_id, "parse_run_id": run.inputs["kinds"][kind]["parse_run_id"],
                                   "resolution": d.resolution, "match_type": d.match_type, "llm_used": d.llm_used,
                                   "manual_action": d.manual_action, "resolver_version": run.resolver_version, "policy_hash": run.policy_hash} for d in members]
                row.updated_at = datetime.utcnow()
                if kind == "characters":
                    for decision in members:
                        for proposal in decision.candidate["chapter_appearances"]:
                            old = db.query(AppearanceEvent).filter_by(candidate_id=decision.candidate_id, event_key=proposal["event_key"]).first()
                            values = {"novel_id": run.novel_id, "chapter_id": run.chapter_id, "character_id": asset_id,
                                "candidate_id": decision.candidate_id, "resolution_run_id": run.id,
                                "event_key": proposal["event_key"], "change_type": proposal["change_type"].upper(),
                                "appearance_description": proposal["appearance_description"], "source_evidence": proposal["source_evidence"],
                                "source_start": None, "source_end": None, "status": "PENDING_LOCATION"}
                            if old:
                                if old.character_id != asset_id:
                                    raise ResolutionFailure("APPEARANCE_IDENTITY_CHANGED")
                                old.resolution_run_id = run.id
                            else:
                                db.add(AppearanceEvent(**values))
            for asset_id, omission in carries.items():
                snapshot = omission.proof["parent_binding"]
                row = db.query(model).filter_by(chapter_id=run.chapter_id, **{fk: asset_id}).first()
                if not row or row.id != omission.prior_binding_id or omission.proof_hash != digest(omission.proof):
                    raise ResolutionFailure("CARRY_PARENT_BINDING_CHANGED")
                row.status, row.resolution_run_id = "RESOLVED", run.id
                row.chapter_role = snapshot.get("chapter_role")
                row.resolution_method = "SOURCE_EVIDENCE_CARRY_FORWARD"
                row.resolution_confidence = snapshot["resolution_confidence"]
                row.source_evidence = deepcopy(snapshot["source_evidence"])
                row.provenance = deepcopy(snapshot["provenance"]) + [{
                    "omission_id": omission.id, "origin": "SAME_SOURCE_CARRY_FORWARD",
                    "prior_binding_id": omission.prior_binding_id,
                    "prior_resolution_run_id": omission.prior_resolution_run_id,
                    "source_hash": run.inputs["source_hash"], "resolver_version": run.resolver_version,
                    "policy_hash": run.policy_hash, "proof_hash": omission.proof_hash}]
                row.updated_at = datetime.utcnow()

    def review(self, novel_id, chapter_id, decision_id, action):
        db = self.db
        decision = db.get(Decision, decision_id)
        run = db.get(Run, decision.run_id) if decision else None
        if not run or run.novel_id != novel_id or run.chapter_id != chapter_id:
            raise HTTPException(404, "歧义项不存在")
        owner = str(uuid4())
        acquire(db, novel_id, owner, 120)
        try:
            db.expire_all()
            fence(db, novel_id, owner)
            decision, run = db.get(Decision, decision_id), db.get(Run, run.id)
            chapter, task = self._lock_publication_scope(run, [decision.asset_type])
            current = resolution_response(db, run)
            if (current["effectiveStatus"] != "NEEDS_REVIEW"
                    or decision.id not in {row["id"] for row in current["reviews"]}
                    or decision.status != "PENDING_REVIEW"):
                raise HTTPException(409, "歧义记录已处理或来源已变化，请刷新")
            if catalog(db, novel_id)[1] != action.expected_catalog_hash:
                raise HTTPException(409, "资产库已变化，请刷新候选再确认")
            policy = load_policy()
            self._assert_parent_baseline(run, [decision.asset_type])
            decision.manual_action = {"action": action.action, "asset_id": action.asset_id, "canonical_name": action.canonical_name,
                                      "confirm_legacy_type": action.confirm_legacy_type, "at": datetime.utcnow().isoformat()}
            if action.action == "IGNORE":
                decision.status = "IGNORED"
            elif action.action == "MATCH":
                if not action.asset_id:
                    raise HTTPException(422, "请选择已有资产")
                self._apply(decision, run, policy, chapter, target_id=action.asset_id, confirm_type=action.confirm_legacy_type)
                decision.resolution, decision.match_type = "EXISTING", "MANUAL"
            else:
                name = (action.canonical_name or "").strip()
                if not name or (decision.asset_type == "characters" and decision.candidate["entity_type"] == "GROUP"
                                and name in policy["rules"]["generic_groups"]):
                    raise HTTPException(422, "泛GROUP创建必须输入带地点或归属的稳定规范名")
                self._apply(decision, run, policy, chapter, create_name=name)
                decision.resolution, decision.match_type = "NEW", "MANUAL"
            db.flush()
            decisions = db.query(Decision).filter_by(run_id=run.id).all()
            self._reconcile_kind(run, decisions, decision.asset_type)
            pending = any(_pending_kind(db, run.id, kind) for kind in run.kinds)
            run.status = "NEEDS_REVIEW" if pending else "SUCCEEDED"
            run.issues = self._pending_issues(run, decisions)
            run.completed_at = datetime.utcnow()
            if task:
                task.current_step = "存在歧义或资产遗漏，等待检查" if pending else "章回身份归并完成（人工处理）"
            db.flush()
            _, final_inputs, _ = current_inputs(db, novel_id, chapter_id, [decision.asset_type])
            if not _parse_inputs_equal(run.inputs, final_inputs, [decision.asset_type]):
                raise HTTPException(409, "原文或解析候选已变化，请刷新")
            db.commit()
            data = resolution_response(db, run)
            return {"success": True, "data": data}
        finally:
            release(db, novel_id, owner)
