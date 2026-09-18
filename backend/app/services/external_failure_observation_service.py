"""Independent append-only storage and retention for Stage B observations."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import re
from threading import Lock

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.external_failure_observation import ExternalFailureObservation
from app.models.task import Task
from app.services.external_failure_diagnostic import (
    ExternalFailureDiagnostic,
    canonical_json_bytes,
)


MAX_DIAGNOSTIC_BYTES = 8 * 1024
MAX_SUMMARY_BYTES = 1024
RETENTION_DAYS = 90
RETENTION_ROWS = 10_000
RETENTION_LOGICAL_BYTES = 128 * 1024 * 1024
RETENTION_BATCH = 500
_DIAGNOSTIC_ID = re.compile(r"efd1_([0-9a-f]{64})")
_retention_lock = Lock()
_last_retention_day = None
_inserts_since_retention = 0


class ObservationConflict(RuntimeError):
    """The deterministic operation key was reused with different evidence."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def _bounded_summary(diagnostic: dict) -> str:
    summary = f"{diagnostic['error_code']}: {diagnostic['failure_class']}"
    encoded = summary.encode("utf-8")
    if len(encoded) <= MAX_SUMMARY_BYTES:
        return summary
    return encoded[:MAX_SUMMARY_BYTES].decode("utf-8", errors="ignore")


def safe_observation_diagnostic(diagnostic: dict) -> dict:
    """Re-validate and re-redact a Stage A compact diagnostic at the Stage B boundary."""
    required = (
        "diagnostic_id", "error_code", "failure_class", "level", "stage",
        "operation", "service", "scope", "timing", "reference", "upstream",
        "external_call", "submission", "evidence",
    )
    if (not isinstance(diagnostic, dict) or diagnostic.get("version") != 1
            or any(key not in diagnostic for key in required)
            or any(not isinstance(diagnostic.get(key), str) or not diagnostic[key]
                   for key in ("diagnostic_id", "error_code", "failure_class", "level", "stage", "operation", "service"))
            or any(not isinstance(diagnostic.get(key), dict) for key in (
                "scope", "timing", "reference", "upstream", "external_call", "submission", "evidence",
            ))):
        raise ValueError("INVALID_OBSERVATION_DIAGNOSTIC")
    diagnostic_id = str(diagnostic.get("diagnostic_id") or "")
    if not _DIAGNOSTIC_ID.fullmatch(diagnostic_id):
        raise ValueError("INVALID_OBSERVATION_DIAGNOSTIC_ID")
    rebuilt = ExternalFailureDiagnostic.build(
        operation_key={"stage_b_existing_diagnostic_id": diagnostic_id},
        error_code=diagnostic.get("error_code"),
        failure_class=diagnostic.get("failure_class"),
        level=diagnostic.get("level"),
        stage=diagnostic.get("stage"),
        operation=diagnostic.get("operation"),
        service=diagnostic.get("service"),
        provider=diagnostic.get("provider"),
        scope=diagnostic.get("scope"),
        timing=diagnostic.get("timing"),
        reference=diagnostic.get("reference"),
        upstream=diagnostic.get("upstream"),
        external_call=diagnostic.get("external_call"),
        submission=diagnostic.get("submission"),
        evidence=diagnostic.get("evidence"),
        maximum=MAX_DIAGNOSTIC_BYTES,
    )
    rebuilt["diagnostic_id"] = diagnostic_id
    rebuilt["redacted"] = rebuilt["redacted"] or diagnostic.get("redacted") is True
    rebuilt["truncated"] = rebuilt["truncated"] or diagnostic.get("truncated") is True
    return ExternalFailureDiagnostic.compact(rebuilt)


def _normalized_values(diagnostic: dict, *, recorded_at: datetime | None = None) -> dict:
    compact = safe_observation_diagnostic(deepcopy(diagnostic))
    match = _DIAGNOSTIC_ID.fullmatch(str(compact.get("diagnostic_id") or ""))
    if not match:
        raise ValueError("INVALID_OBSERVATION_DIAGNOSTIC_ID")
    encoded = canonical_json_bytes(compact)
    if len(encoded) > MAX_DIAGNOSTIC_BYTES:
        raise ValueError("OBSERVATION_DIAGNOSTIC_TOO_LARGE")

    scope = compact.get("scope") or {}
    timing = compact.get("timing") or {}
    call = compact.get("external_call") or {}
    submission = compact.get("submission") or {}
    evidence = compact.get("evidence") or {}
    occurred_at = _parse_time(timing.get("finished_at") or timing.get("started_at"))
    recorded_at = _utc(recorded_at or datetime.now(timezone.utc))
    occurred_at = occurred_at or recorded_at
    return {
        "id": compact["diagnostic_id"],
        "schema_version": 1,
        "dedupe_key": match.group(1),
        "occurred_at": occurred_at,
        "recorded_at": recorded_at,
        "level": compact["level"],
        "service": compact["service"],
        "provider": compact.get("provider"),
        "stage": compact["stage"],
        "operation": compact["operation"],
        "error_code": compact["error_code"],
        "failure_class": compact["failure_class"],
        "novel_id": scope.get("book_id"),
        "chapter_id": scope.get("chapter_id"),
        "shot_id": scope.get("shot_id"),
        "shot_index": scope.get("shot_index"),
        "clip_index": scope.get("clip_index"),
        "frame_index": scope.get("frame_index"),
        "reference_index": scope.get("reference_index"),
        "task_id": scope.get("task_id"),
        "attempt_kind": scope.get("attempt_kind"),
        "attempt_id": scope.get("attempt_id"),
        "attempt_no": scope.get("attempt_no"),
        "retry_no": scope.get("retry_no"),
        "http_status": call.get("http_status"),
        "submission_state": submission.get("state"),
        "cid": submission.get("cid"),
        "summary": _bounded_summary(compact),
        "diagnostic_json": encoded.decode("utf-8"),
        "evidence_id": evidence.get("evidence_id"),
        "evidence_path": evidence.get("path"),
        "evidence_sha256": evidence.get("sha256"),
        "evidence_bytes": evidence.get("bytes"),
    }


def append_external_failure_observation(db, diagnostic: dict, *, recorded_at: datetime | None = None):
    """Append one observation; idempotent equality is exact canonical safe evidence."""
    values = _normalized_values(diagnostic, recorded_at=recorded_at)
    existing = db.execute(
        select(ExternalFailureObservation).where(
            ExternalFailureObservation.dedupe_key == values["dedupe_key"]
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.diagnostic_json != values["diagnostic_json"]:
            raise ObservationConflict("EXTERNAL_FAILURE_OBSERVATION_DEDUPE_CONFLICT")
        return existing, False

    row = ExternalFailureObservation(**values)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = db.execute(
            select(ExternalFailureObservation).where(
                ExternalFailureObservation.dedupe_key == values["dedupe_key"]
            )
        ).scalar_one_or_none()
        if existing is None or existing.diagnostic_json != values["diagnostic_json"]:
            raise ObservationConflict("EXTERNAL_FAILURE_OBSERVATION_DEDUPE_CONFLICT")
        return existing, False
    return row, True


def _logical_bytes(row) -> int:
    return (
        len((row.summary or "").encode("utf-8"))
        + len((row.diagnostic_json or "").encode("utf-8"))
        + max(0, int(row.evidence_bytes or 0))
    )


def enforce_observation_retention(
    db,
    *,
    now: datetime | None = None,
    max_age_days: int = RETENTION_DAYS,
    max_rows: int = RETENTION_ROWS,
    max_logical_bytes: int = RETENTION_LOGICAL_BYTES,
    batch_size: int = RETENTION_BATCH,
) -> int:
    """Delete only the oldest observations required by the configured bounds."""
    if min(max_age_days, max_rows, max_logical_bytes, batch_size) < 0 or batch_size > RETENTION_BATCH:
        raise ValueError("INVALID_OBSERVATION_RETENTION_LIMIT")
    now = _utc(now or datetime.now(timezone.utc))
    rows = db.execute(
        select(
            ExternalFailureObservation.id,
            ExternalFailureObservation.occurred_at,
            ExternalFailureObservation.summary,
            ExternalFailureObservation.diagnostic_json,
            ExternalFailureObservation.evidence_bytes,
        ).order_by(
            ExternalFailureObservation.occurred_at.asc(),
            ExternalFailureObservation.id.asc(),
        )
    ).all()
    cutoff = now - timedelta(days=max_age_days)
    age_count = sum(1 for row in rows if _utc(row.occurred_at) < cutoff)
    count_excess = max(0, len(rows) - max_rows)
    total_bytes = sum(_logical_bytes(row) for row in rows)
    byte_count = 0
    while byte_count < len(rows) and total_bytes > max_logical_bytes:
        total_bytes -= _logical_bytes(rows[byte_count])
        byte_count += 1
    delete_count = min(max(age_count, count_excess, byte_count), batch_size)
    if delete_count:
        ids = [row.id for row in rows[:delete_count]]
        db.query(ExternalFailureObservation).filter(
            ExternalFailureObservation.id.in_(ids)
        ).delete(synchronize_session=False)
    return delete_count


def run_observation_retention_best_effort(*, session_factory=None, now: datetime | None = None) -> None:
    """Run at most once per UTC day and never expose failure to business code."""
    global _last_retention_day
    now = _utc(now or datetime.now(timezone.utc))
    with _retention_lock:
        if _last_retention_day == now.date():
            return
        factory = session_factory or SessionLocal
        db = None
        try:
            db = factory()
            enforce_observation_retention(db, now=now)
            db.commit()
        except Exception:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            return
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass
        _last_retention_day = now.date()


def _count_insert_for_retention(session_factory) -> None:
    global _inserts_since_retention
    with _retention_lock:
        _inserts_since_retention += 1
        due = _inserts_since_retention >= 100
        if due:
            _inserts_since_retention = 0
    if due:
        run_observation_retention_best_effort(session_factory=session_factory)


def record_external_failure_best_effort(
    diagnostic: dict,
    *,
    session_factory=None,
    recorded_at: datetime | None = None,
) -> None:
    """Use an independent transaction and deliberately return no business decision."""
    factory = session_factory or SessionLocal
    db = None
    inserted = False
    try:
        db = factory()
        _, inserted = append_external_failure_observation(db, diagnostic, recorded_at=recorded_at)
        db.commit()
    except Exception:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
    if inserted:
        _count_insert_for_retention(factory)


def _task_diagnostics(metadata_json: str | None) -> list[dict]:
    try:
        metadata = json.loads(metadata_json or "{}")
    except (TypeError, ValueError):
        return []
    clips = ((metadata.get("video_run") or {}).get("clips") or {}) if isinstance(metadata, dict) else {}
    if not isinstance(clips, dict):
        return []
    diagnostics = []
    for key in sorted(clips, key=str):
        slot = clips.get(key)
        diagnostic = slot.get("external_failure") if isinstance(slot, dict) else None
        if isinstance(diagnostic, dict):
            diagnostics.append(diagnostic)
    return diagnostics


def record_task_external_failures_best_effort(task_id: str, *, session_factory=None) -> None:
    """Observe only one just-finished Task; this is not a historical backfill scan."""
    factory = session_factory or SessionLocal
    db = None
    try:
        db = factory()
        row = db.execute(
            select(Task.status, Task.metadata_json).where(Task.id == task_id)
        ).first()
        diagnostics = _task_diagnostics(row.metadata_json) if row and row.status in {"failed", "cancelled"} else []
    except Exception:
        diagnostics = []
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
    for diagnostic in diagnostics:
        record_external_failure_best_effort(diagnostic, session_factory=factory)


async def run_next_video_task_with_observation() -> bool:
    """Run the exact selected Task through frozen Stage A, then observe that Task only."""
    from app.services.shot_video_execution import run_video_execution

    task_id = None
    db = SessionLocal()
    try:
        if db.execute(select(Task.id).where(
            Task.type == "shot_video", Task.status == "running"
        ).limit(1)).scalar_one_or_none():
            return False
        task_id = db.execute(select(Task.id).where(
            Task.type == "shot_video", Task.status == "pending"
        ).order_by(Task.created_at.asc(), Task.id.asc()).limit(1)).scalar_one_or_none()
        if task_id is None:
            return False
        await run_video_execution(db, task_id)
    finally:
        db.close()
    if task_id:
        record_task_external_failures_best_effort(task_id)
    return True


__all__ = [
    "MAX_DIAGNOSTIC_BYTES", "MAX_SUMMARY_BYTES", "ObservationConflict",
    "append_external_failure_observation", "enforce_observation_retention",
    "record_external_failure_best_effort", "record_task_external_failures_best_effort",
    "run_next_video_task_with_observation", "run_observation_retention_best_effort",
    "safe_observation_diagnostic",
]
