"""Explicit publication purpose and private working state for generation attempts."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4


_TASK_EVIDENCE_FIELDS = ("workflow_id", "workflow_name", "comfyui_prompt_id", "prompt_text", "workflow_json", "reference_images", "video_director_clips")
_REVIEW_FINDINGS_KEY = "review_findings"
_REVIEW_FINDINGS_VERSION = 1
_REVIEW_CODE = "UNBOUND_ASSET_REFERENCE"
_REVIEW_ACTION = "RETRY_PROMPT_ONCE_SAME_FROZEN_INPUTS"
_REVIEW_MESSAGE = "Fresh keyframe prompt contained an asset reference not bound to the frozen manifest."
_REVIEW_EVIDENCE_FIELDS = (
    "attempt_execution_path", "first_failed_llm_log_id", "first_response_sha256",
    "frozen_input_sha256", "manifest_sha256", "rsa_hash", "template_sha256",
)
_REVIEW_EVIDENCE_PUBLIC_FIELDS = (
    ("attemptExecutionPath", "attempt_execution_path"),
    ("firstFailedLlmLogId", "first_failed_llm_log_id"),
    ("firstResponseSha256", "first_response_sha256"),
    ("frozenInputSha256", "frozen_input_sha256"),
    ("manifestSha256", "manifest_sha256"),
    ("rsaHash", "rsa_hash"),
    ("templateSha256", "template_sha256"),
)


class ExecutionConflict(RuntimeError):
    pass


def metadata(task):
    value = getattr(task, "metadata_json", None)
    try:
        value = {} if value is None or value == "" else json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError) as exc:
        raise ExecutionConflict("INVALID_EXECUTION_METADATA") from exc
    if not isinstance(value, dict):
        raise ExecutionConflict("INVALID_EXECUTION_METADATA")
    return deepcopy(value)


def upsert_review_finding(db, task_id, *, code, message=None, evidence=None,
                          fallback_outcome="PENDING", claim_token=None, terminal=False, commit=True):
    """Store the sole v1 review finding without accepting caller-owned scope IDs."""
    from app.models.rsa_media import RsaImageAttempt
    from app.models.shot import Shot
    from app.models.task import Task

    if code != _REVIEW_CODE or fallback_outcome not in {"PENDING", "SUCCEEDED", "FAILED"}:
        raise ExecutionConflict("REVIEW_FINDING_NOT_ALLOWED")
    task = db.get(Task, task_id)
    attempt = db.get(RsaImageAttempt, task_id)
    if (not task or not attempt or attempt.id != task.id or attempt.shot_id != task.shot_id
            or attempt.novel_id != task.novel_id or attempt.chapter_id != task.chapter_id
            or attempt.stage != "KEYFRAME" or type(attempt.frame_index) is not int or attempt.frame_index < 0):
        raise ExecutionConflict("REVIEW_FINDING_SCOPE_UNVERIFIED")
    shot = db.get(Shot, task.shot_id) if task.shot_id else None
    stable_scope = {
        "book_id": task.novel_id,
        "chapter_id": task.chapter_id,
        "shot_id": task.shot_id,
        "clip_index": None,
        "frame_index": attempt.frame_index,
        "task_id": task.id,
    }
    identity = json.dumps({**stable_scope, "attempt_id": attempt.id, "code": code}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    finding_id = "review-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    old_metadata = task.metadata_json
    saved = metadata(task)
    envelope = saved.get(_REVIEW_FINDINGS_KEY, {"version": _REVIEW_FINDINGS_VERSION, "items": []})
    if (not isinstance(envelope, dict) or set(envelope) != {"version", "items"}
            or envelope.get("version") != _REVIEW_FINDINGS_VERSION or not isinstance(envelope.get("items"), list)):
        raise ExecutionConflict("INVALID_REVIEW_FINDINGS")
    findings = envelope["items"]
    matches = [item for item in findings if isinstance(item, dict) and item.get("id") == finding_id]
    if len(matches) > 1:
        raise ExecutionConflict("DUPLICATE_REVIEW_FINDING")
    existing = matches[0] if matches else None
    if claim_token is not None:
        if (terminal or task.status != "running" or attempt.status != "RUNNING"
                or task.claim_token != claim_token or attempt.claim_token != claim_token):
            raise ExecutionConflict("REVIEW_FINDING_OWNERSHIP_CHANGED")
    elif terminal:
        if task.status not in {"failed", "cancelled"} or attempt.status not in {"PENDING", "RUNNING"} or not existing:
            raise ExecutionConflict("REVIEW_FINDING_TERMINAL_SCOPE_CHANGED")
    elif not existing or existing.get("fallback_outcome") != fallback_outcome:
        raise ExecutionConflict("REVIEW_FINDING_OWNER_REQUIRED")
    if evidence is not None:
        if (not isinstance(evidence, dict) or set(evidence) != set(_REVIEW_EVIDENCE_FIELDS)
                or evidence.get("attempt_execution_path") != "RsaImageAttempt.execution.prompt_attempts[0]"
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", evidence.get("first_failed_llm_log_id", ""))
                or any(not re.fullmatch(r"[0-9a-f]{64}", evidence.get(key, "")) for key in
                       ("first_response_sha256", "frozen_input_sha256", "manifest_sha256", "rsa_hash", "template_sha256"))):
            raise ExecutionConflict("INVALID_REVIEW_FINDING_EVIDENCE")
        evidence = deepcopy(evidence)
    if existing:
        immutable = {**stable_scope, "id": finding_id, "severity": "REVIEW_REQUIRED", "code": code,
                     "message": _REVIEW_MESSAGE, "fallback_action": _REVIEW_ACTION, "status": "OPEN"}
        if any(existing.get(key) != value for key, value in immutable.items()):
            raise ExecutionConflict("REVIEW_FINDING_SCOPE_CHANGED")
        if message is not None and message != _REVIEW_MESSAGE:
            raise ExecutionConflict("REVIEW_FINDING_MESSAGE_CHANGED")
        if evidence is not None and existing.get("evidence") != evidence:
            raise ExecutionConflict("REVIEW_FINDING_EVIDENCE_CHANGED")
        previous = existing.get("fallback_outcome")
        if previous not in {"PENDING", "SUCCEEDED", "FAILED"} or (previous != "PENDING" and previous != fallback_outcome):
            raise ExecutionConflict("REVIEW_FINDING_OUTCOME_CHANGED")
        finding = {**existing, "fallback_outcome": fallback_outcome}
    else:
        if not shot or fallback_outcome != "PENDING" or message != _REVIEW_MESSAGE or evidence is None:
            raise ExecutionConflict("REVIEW_FINDING_INITIAL_STATE_INVALID")
        finding = {
            "id": finding_id,
            **stable_scope,
            "shot_index": shot.index,
            "severity": "REVIEW_REQUIRED",
            "code": code,
            "message": _REVIEW_MESSAGE,
            "evidence": evidence,
            "fallback_action": _REVIEW_ACTION,
            "status": "OPEN",
            "fallback_outcome": "PENDING",
        }
    if existing and existing == finding:
        return deepcopy(finding)
    saved[_REVIEW_FINDINGS_KEY] = {
        "version": _REVIEW_FINDINGS_VERSION,
        "items": [item for item in findings if not (isinstance(item, dict) and item.get("id") == finding_id)] + [finding],
    }
    encoded = json.dumps(saved, ensure_ascii=False, allow_nan=False)
    query = db.query(Task).filter(Task.id == task.id, Task.metadata_json == old_metadata)
    if claim_token is not None:
        query = query.filter(Task.status == "running", Task.claim_token == claim_token)
    elif terminal:
        query = query.filter(Task.status.in_(["failed", "cancelled"]))
    if query.update({"metadata_json": encoded}, synchronize_session=False) != 1:
        raise ExecutionConflict("REVIEW_FINDING_WRITE_CONFLICT")
    db.expire(task, ["metadata_json"])
    if commit:
        db.commit()
        db.refresh(task)
    return deepcopy(finding)


def public_review_findings(task):
    """Project only the compact review contract, never arbitrary metadata fields."""
    try:
        envelope = metadata(task).get(_REVIEW_FINDINGS_KEY, {"version": _REVIEW_FINDINGS_VERSION, "items": []})
    except ExecutionConflict:
        return []
    if (not isinstance(envelope, dict) or envelope.get("version") != _REVIEW_FINDINGS_VERSION
            or not isinstance(envelope.get("items"), list)):
        return []
    fields = (
        ("findingId", "id"), ("bookId", "book_id"), ("chapterId", "chapter_id"),
        ("shotId", "shot_id"), ("shotIndex", "shot_index"), ("clipIndex", "clip_index"),
        ("frameIndex", "frame_index"), ("taskId", "task_id"), ("severity", "severity"),
        ("code", "code"), ("message", "message"), ("fallbackAction", "fallback_action"),
        ("status", "status"), ("fallbackOutcome", "fallback_outcome"),
    )
    result = []
    for finding in envelope["items"]:
        if not isinstance(finding, dict):
            continue
        evidence = finding.get("evidence")
        result.append({**{public: finding.get(saved) for public, saved in fields},
                       "evidence": {public: evidence.get(saved) for public, saved in _REVIEW_EVIDENCE_PUBLIC_FIELDS}
                       if isinstance(evidence, dict) else {}})
    from app.services.evidence_reader import safe_value
    return safe_value(result)


def execution_purpose(task):
    saved = metadata(task)
    if "execution" in saved and "execution_purpose" not in saved:
        raise ExecutionConflict("EXECUTION_PURPOSE_REQUIRED")
    value = saved.get("execution_purpose", "production")
    if not isinstance(value, str) or value not in {"production", "benchmark"}:
        raise ExecutionConflict("INVALID_EXECUTION_PURPOSE")
    return value


def is_benchmark(task):
    return execution_purpose(task) == "benchmark"


def execution_record(task):
    value = metadata(task).get("execution")
    if value is None and not is_benchmark(task):
        return None
    if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1
            or not isinstance(value.get("attempt_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", value["attempt_id"])
            or not isinstance(value.get("shot_snapshot"), dict) or not isinstance(value.get("working_shot"), dict)
            or type(value.get("revision")) is not int or value["revision"] < 0):
        raise ExecutionConflict("INVALID_EXECUTION_CONTRACT")
    if any(value["shot_snapshot"].get(key) != value["working_shot"].get(key) for key in ("id", "chapter_id")):
        raise ExecutionConflict("EXECUTION_TARGET_CHANGED")
    if value["shot_snapshot"].get("id") != task.shot_id or value["shot_snapshot"].get("chapter_id") != task.chapter_id:
        raise ExecutionConflict("EXECUTION_TASK_REPLACED")
    return value


def create_execution_metadata(shot, *, purpose="production", request=None):
    if not isinstance(purpose, str) or purpose not in {"production", "benchmark"}:
        raise ExecutionConflict("INVALID_EXECUTION_PURPOSE")
    from app.models.shot import Shot
    snapshot = {column.key: getattr(shot, column.key, None) for column in Shot.__table__.columns}
    snapshot = {key: value.isoformat() if isinstance(value, datetime) else value for key, value in snapshot.items()}
    return {"execution_purpose": purpose, "execution": {
        "version": 1, "attempt_id": uuid4().hex, "request": deepcopy(request or {}),
        "shot_snapshot": snapshot, "working_shot": deepcopy(snapshot), "revision": 0,
    }}


def load_execution_shot(task):
    record = execution_record(task)
    if record is None:
        raise ExecutionConflict("EXECUTION_CONTRACT_REQUIRED")
    return SimpleNamespace(**deepcopy(record["working_shot"]), _execution_task_id=task.id,
                           _execution_attempt_id=record["attempt_id"], _execution_revision=record["revision"],
                           _execution_purpose=execution_purpose(task), _execution_claim_token=task.claim_token,
                           _execution_task_attempt=task.attempt, _execution_task_type=task.type,
                           _execution_novel_id=task.novel_id, _execution_parent_id=task.parent_task_id,
                           _execution_record=deepcopy(record),
                           _execution_task_evidence={key: getattr(task, key) for key in _TASK_EVIDENCE_FIELDS})


def artifact_directory(task):
    from app.services.file_storage import file_storage
    record = execution_record(task)
    if record is None:
        raise ExecutionConflict("EXECUTION_CONTRACT_REQUIRED")
    if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value)
           for value in (task.id, task.novel_id, task.chapter_id)):
        raise ExecutionConflict("INVALID_TASK_ARTIFACT_ID")
    group = "benchmarks" if is_benchmark(task) else "executions"
    path = file_storage._get_story_dir(task.novel_id) / f"chapter_{task.chapter_id[:8]}" / group / task.id / record["attempt_id"]
    path = path.resolve()
    if not path.is_relative_to(Path(file_storage.base_dir).resolve()):
        raise ExecutionConflict("INVALID_TASK_ARTIFACT_DIRECTORY")
    path.mkdir(parents=True, exist_ok=True)
    return path


def persist_execution_shot(db, task, shot, **task_fields):
    """CAS a private working copy; never flush or restore a production Shot."""
    return persist_execution_state(db, task, shot, {}, **task_fields)


def assert_execution_active(db, task, shot):
    """Recheck the captured actor before I/O or a conditional Task-only write."""
    from app.models.task import Task
    from app.models.shot import Shot
    if shot._execution_purpose == "benchmark" and any(
        isinstance(item, Shot) for item in (*db.new, *db.dirty, *db.deleted)
    ):
        raise ExecutionConflict("PRODUCTION_SHOT_DIRTY")
    task_id = shot._execution_task_id
    with db.no_autoflush:
        current = db.query(Task).filter(Task.id == task_id).populate_existing().first()
        if current is None or current.status not in {"pending", "running"}:
            raise ExecutionConflict("EXECUTION_NOT_ACTIVE")
        record = execution_record(current)
        if (task.id != task_id or record is None
                or record["attempt_id"] != shot._execution_attempt_id or record["revision"] != shot._execution_revision
                or record != shot._execution_record
                or execution_purpose(current) != shot._execution_purpose
                or current.claim_token != shot._execution_claim_token or current.attempt != shot._execution_task_attempt
                or current.type != shot._execution_task_type or current.novel_id != shot._execution_novel_id
                or current.parent_task_id != shot._execution_parent_id
                or {key: getattr(current, key) for key in _TASK_EVIDENCE_FIELDS} != shot._execution_task_evidence
                or shot.id != current.shot_id or shot.chapter_id != current.chapter_id):
            raise ExecutionConflict("EXECUTION_OWNERSHIP_CHANGED")
        if current.parent_task_id:
            parent = db.query(Task).filter(Task.id == current.parent_task_id).populate_existing().first()
            if not parent or parent.status not in {"pending", "running"} or execution_purpose(parent) != execution_purpose(current):
                raise ExecutionConflict("EXECUTION_PARENT_NOT_ACTIVE")
        return current


def persist_execution_state(db, task, shot, execution_updates, **task_fields):
    """Persist working state and attempt evidence in the same Task metadata CAS."""
    from app.models.task import Task
    from sqlalchemy.orm import aliased
    if set(execution_updates) & {"version", "attempt_id", "request", "shot_snapshot", "working_shot", "revision"}:
        raise ExecutionConflict("EXECUTION_IDENTITY_IMMUTABLE")
    if set(task_fields) & {"id", "type", "shot_id", "chapter_id", "novel_id", "parent_task_id", "metadata_json"}:
        raise ExecutionConflict("EXECUTION_TASK_IDENTITY_IMMUTABLE")
    with db.no_autoflush:
        current = assert_execution_active(db, task, shot)
        record = execution_record(current)
        original = current.metadata_json
        updated = metadata(current)
        record["working_shot"] = {key: deepcopy(getattr(shot, key, None)) for key in record["shot_snapshot"]}
        record.update(deepcopy(execution_updates))
        record["revision"] += 1
        updated["execution"] = record
        fields = {**task_fields, "metadata_json": json.dumps(updated, ensure_ascii=False, allow_nan=False)}
        conditions = [Task.id == current.id, Task.status == current.status, Task.metadata_json == original,
                      Task.claim_token == shot._execution_claim_token, Task.attempt == shot._execution_task_attempt,
                      Task.type == current.type, Task.shot_id == shot.id, Task.chapter_id == shot.chapter_id,
                      Task.novel_id == current.novel_id, Task.parent_task_id == current.parent_task_id]
        conditions.extend(getattr(Task, key) == getattr(current, key) for key in _TASK_EVIDENCE_FIELDS)
        if current.parent_task_id:
            parent = aliased(Task)
            conditions.append(db.query(parent.id).filter(parent.id == current.parent_task_id, parent.status.in_(["pending", "running"])).exists())
        try:
            count = db.query(Task).filter(*conditions).update(fields, synchronize_session=False)
            if count != 1:
                raise ExecutionConflict("EXECUTION_WRITE_CONFLICT")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        db.refresh(current)
        shot._execution_revision = record["revision"]
        shot._execution_record = deepcopy(record)
        shot._execution_task_evidence = {key: getattr(current, key) for key in _TASK_EVIDENCE_FIELDS}
        return current


def record_execution_observation(db, task_id, shot, error, *, artifact_url=None, source_url=None, details=None):
    """Retain detached evidence without replacing a terminal/newer attempt."""
    from app.models.task import Task
    from app.models.shot import Shot
    if any(isinstance(item, Shot) for item in (*db.new, *db.dirty, *db.deleted)):
        raise ExecutionConflict("PRODUCTION_SHOT_DIRTY")
    observation = {"attempt_id": shot._execution_attempt_id, "revision": shot._execution_revision,
                   "at": datetime.utcnow().isoformat(), "error": str(error),
                   "artifact_url": artifact_url, "source_url": source_url}
    if details is not None:
        observation["details"] = deepcopy(details)
    for _ in range(3):
        current = db.query(Task).filter(Task.id == task_id).populate_existing().first()
        if current is None:
            return False
        original = current.metadata_json
        value = metadata(current)
        observations = value.setdefault("execution_observations", [])
        if not isinstance(observations, list):
            raise ExecutionConflict("INVALID_EXECUTION_OBSERVATIONS")
        observations.append(observation)
        try:
            count = db.query(Task).filter(Task.id == task_id, Task.status == current.status, Task.metadata_json == original).update(
                {"metadata_json": json.dumps(value, ensure_ascii=False, allow_nan=False)}, synchronize_session=False)
            if count == 1:
                db.commit()
                db.refresh(current)
                return True
        except BaseException:
            db.rollback()
            raise
        db.rollback()
    raise ExecutionConflict("EXECUTION_OBSERVATION_CONFLICT")
