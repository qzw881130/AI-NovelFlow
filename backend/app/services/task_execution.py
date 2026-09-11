"""Explicit publication purpose and private working state for generation attempts."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4


_TASK_EVIDENCE_FIELDS = ("workflow_id", "workflow_name", "comfyui_prompt_id", "prompt_text", "workflow_json", "reference_images", "video_director_clips")


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
