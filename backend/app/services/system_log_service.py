"""Read-only System Logs projection over explicit persisted adapters."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import re

from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.models.external_failure_observation import ExternalFailureObservation
from app.models.llm_log import LLMLog
from app.models.task import Task
from app.services.external_failure_diagnostic import FAILURE_CLASSES, canonical_json_bytes
from app.services.external_failure_observation_service import safe_observation_diagnostic


SOURCE_RANK = {
    "external_failure_observation": 50,
    "task_compact_diagnostic": 40,
    "review_finding": 30,
    "task_terminal": 20,
    "llm_lifecycle": 10,
}
VIEWS = frozenset({"all", "errors", "needs_review", "attention"})
QUALITY = frozenset({
    "STRUCTURED_V1",
    "LEGACY_SUMMARY_ONLY",
    "TIMESTAMP_FALLBACK",
    "UNKNOWN_SUBMISSION_STATE",
    "NOT_SUBMITTED_PROVEN",
})
TERMINAL_TASK_STATUSES = ("completed", "failed", "cancelled")
_DIAGNOSTIC_ID = re.compile(r"efd1_[0-9a-f]{64}")
_ERROR_CODE = re.compile(r"([A-Z][A-Z0-9_]{0,127})(?::|$)")
_SAFE_LABEL = re.compile(r"[A-Za-z0-9_.:/ -]{1,128}")
_REVIEW_ID = re.compile(r"review-[0-9a-f]{32}")
_HASH = re.compile(r"[0-9a-f]{64}")
_PUBLIC_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_REVIEW_CODE = "UNBOUND_ASSET_REFERENCE"
_REVIEW_MESSAGE = "Fresh keyframe prompt contained an asset reference not bound to the frozen manifest."
_REVIEW_ACTION = "RETRY_PROMPT_ONCE_SAME_FROZEN_INPUTS"


def _utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value) -> datetime | None:
    return _utc(value)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _label(value, fallback=None):
    if isinstance(value, str) and _SAFE_LABEL.fullmatch(value):
        return value
    return fallback


def _operation(value, fallback):
    if not isinstance(value, str) or not value:
        return fallback
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value).upper()[:128]
    return normalized or fallback


def _qualities(*values):
    result = []
    for value in values:
        if value in QUALITY and value not in result:
            result.append(value)
    return result


def _scope(*, novel_id=None, chapter_id=None, shot_id=None, shot_index=None, clip_index=None,
           frame_index=None, reference_index=None, task_id=None, attempt_kind=None,
           attempt_id=None, attempt_no=None, retry_no=None):
    return {
        "novelId": novel_id,
        "chapterId": chapter_id,
        "shotId": shot_id,
        "shotIndex": shot_index,
        "clipIndex": clip_index,
        "frameIndex": frame_index,
        "referenceIndex": reference_index,
        "taskId": task_id,
        "attemptKind": attempt_kind,
        "attemptId": attempt_id,
        "attemptNo": attempt_no,
        "retryNo": retry_no,
    }


def _event(*, event_id, source, occurred_at, level, service, provider, stage, operation,
           error_code, failure_class, summary, scope, qualities, submission=None, detail=None):
    flags = _qualities(*qualities)
    return {
        "eventId": event_id,
        "source": source,
        "sourceRank": SOURCE_RANK[source],
        "occurredAt": _iso(occurred_at),
        "level": level,
        "service": service,
        "provider": provider,
        "stage": stage,
        "operation": operation,
        "errorCode": error_code,
        "failureClass": failure_class,
        "summary": summary,
        "scope": scope,
        "submission": submission,
        "diagnosticQuality": flags[0] if flags else None,
        "diagnosticQualityFlags": flags,
        "_sortTime": _utc(occurred_at),
        "_detail": detail,
    }


def _safe_compact(raw) -> dict | None:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        compact = safe_observation_diagnostic(value)
    except (TypeError, ValueError, RecursionError):
        return None
    if not _DIAGNOSTIC_ID.fullmatch(str(compact.get("diagnostic_id") or "")):
        return None
    return compact


def _public_diagnostic(compact):
    scope = compact.get("scope") or {}
    timing = compact.get("timing") or {}
    reference = compact.get("reference") or {}
    upstream = compact.get("upstream") or {}
    call = compact.get("external_call") or {}
    submission = compact.get("submission") or {}
    evidence = compact.get("evidence") or {}
    return {
        "version": compact.get("version"),
        "diagnosticId": compact.get("diagnostic_id"),
        "errorCode": compact.get("error_code"),
        "failureClass": compact.get("failure_class"),
        "level": compact.get("level"),
        "stage": compact.get("stage"),
        "operation": compact.get("operation"),
        "service": compact.get("service"),
        "provider": compact.get("provider"),
        "scope": _scope(
            novel_id=scope.get("book_id"), chapter_id=scope.get("chapter_id"),
            shot_id=scope.get("shot_id"), shot_index=scope.get("shot_index"),
            clip_index=scope.get("clip_index"), frame_index=scope.get("frame_index"),
            reference_index=scope.get("reference_index"), task_id=scope.get("task_id"),
            attempt_kind=scope.get("attempt_kind"), attempt_id=scope.get("attempt_id"),
            attempt_no=scope.get("attempt_no"), retry_no=scope.get("retry_no"),
        ),
        "timing": {
            "startedAt": timing.get("started_at"), "finishedAt": timing.get("finished_at"),
            "elapsedMs": timing.get("elapsed_ms"),
        },
        "reference": {
            "referenceIndex": reference.get("reference_index"), "filename": reference.get("filename"),
            "bytes": reference.get("bytes"), "sha256": reference.get("sha256"),
            "sourceId": reference.get("source_id"), "revision": reference.get("revision"),
        },
        "upstream": {
            "rsaId": upstream.get("rsa_id"), "rsaHash": upstream.get("rsa_hash"),
            "manifestHash": upstream.get("manifest_hash"),
        },
        "externalCall": {
            "endpoint": call.get("endpoint"), "method": call.get("method"),
            "timeoutMs": call.get("timeout_ms"), "exceptionType": call.get("exception_type"),
            "exceptionMessage": call.get("exception_message"), "httpStatus": call.get("http_status"),
            "responseContentType": call.get("response_content_type"),
            "responseBodySha256": call.get("response_body_sha256"),
            "responseBodyBytes": call.get("response_body_bytes"),
            "responseExcerptTruncated": call.get("response_excerpt_truncated"),
            "receiptStatus": call.get("receipt_status"), "receiptViolation": call.get("receipt_violation"),
        },
        "submission": {
            "queueCalled": submission.get("queue_called"), "submitted": submission.get("submitted"),
            "state": submission.get("state"), "cid": submission.get("cid"),
            "queueSeen": submission.get("queue_seen"),
            "remoteUploadEffect": submission.get("remote_upload_effect"),
        },
        "evidence": {
            "evidenceId": evidence.get("evidence_id"), "path": evidence.get("path"),
            "sha256": evidence.get("sha256"), "bytes": evidence.get("bytes"),
            "truncated": evidence.get("truncated"), "redactionVersion": evidence.get("redaction_version"),
        },
        "redacted": compact.get("redacted") is True,
        "truncated": compact.get("truncated") is True,
    }


def _compact_belongs_to_task(compact, task_row):
    scope = compact.get("scope") or {}
    return all((
        scope.get("task_id") == task_row["task_id"],
        scope.get("book_id") == task_row["novel_id"],
        scope.get("chapter_id") == task_row["chapter_id"],
        scope.get("shot_id") == task_row["shot_id"],
    ))


def _diagnostic_event(compact, *, source, event_id, fallback_time, domain=None):
    timing = compact.get("timing") or {}
    occurred = _parse_time(timing.get("finished_at") or timing.get("started_at"))
    timestamp_fallback = occurred is None
    occurred = occurred or _utc(fallback_time)
    if occurred is None:
        return None
    scope = compact.get("scope") or {}
    submission = compact.get("submission") or {}
    state = submission.get("state")
    submission_quality = "NOT_SUBMITTED_PROVEN" if (
        state == "NOT_SUBMITTED"
        and submission.get("queue_called") is False
        and submission.get("submitted") is False
        and submission.get("cid") is None
    ) else "UNKNOWN_SUBMISSION_STATE"
    public_submission = {
        "queueCalled": submission.get("queue_called"),
        "submitted": submission.get("submitted"),
        "state": state,
        "cid": submission.get("cid"),
        "queueSeen": submission.get("queue_seen"),
        "remoteUploadEffect": submission.get("remote_upload_effect"),
    }
    evidence = compact.get("evidence") or {}
    detail = {
        "diagnostic": _public_diagnostic(compact),
        "evidence": {
            "evidenceId": evidence.get("evidence_id"),
            "path": evidence.get("path"),
            "sha256": evidence.get("sha256"),
            "bytes": evidence.get("bytes"),
            "truncated": evidence.get("truncated"),
            "redactionVersion": evidence.get("redaction_version"),
        },
        "domainState": domain,
    }
    return _event(
        event_id=event_id,
        source=source,
        occurred_at=occurred,
        level=compact.get("level"),
        service=compact.get("service"),
        provider=compact.get("provider"),
        stage=compact.get("stage"),
        operation=compact.get("operation"),
        error_code=compact.get("error_code"),
        failure_class=compact.get("failure_class"),
        summary=f"{compact.get('error_code')}: {compact.get('failure_class')}",
        scope=_scope(
            novel_id=scope.get("book_id"), chapter_id=scope.get("chapter_id"),
            shot_id=scope.get("shot_id"), shot_index=scope.get("shot_index"),
            clip_index=scope.get("clip_index"), frame_index=scope.get("frame_index"),
            reference_index=scope.get("reference_index"), task_id=scope.get("task_id"),
            attempt_kind=scope.get("attempt_kind"), attempt_id=scope.get("attempt_id"),
            attempt_no=scope.get("attempt_no"), retry_no=scope.get("retry_no"),
        ),
        qualities=_qualities(
            "STRUCTURED_V1",
            "TIMESTAMP_FALLBACK" if timestamp_fallback else None,
            submission_quality,
        ),
        submission=public_submission,
        detail=detail,
    )


def _public(event: dict, *, detail=False):
    result = {
        key: value for key, value in event.items()
        if not key.startswith("_") and key != "sourceRank"
    }
    if detail:
        result["detail"] = event.get("_detail")
    return result


class SystemLogService:
    """Merge explicit adapters without reconciling or mutating their source records."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _filter_hash(filters):
        payload = {key: value for key, value in filters.items() if key not in {"cursor", "limit"}}
        for key in ("from_time", "to_time"):
            if isinstance(payload.get(key), datetime):
                payload[key] = _iso(payload[key])
        return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()

    @staticmethod
    def _encode_cursor(event, filter_hash):
        payload = {
            "version": 1,
            "occurredAt": event["occurredAt"],
            "sourceRank": event["sourceRank"],
            "eventId": event["eventId"],
            "filterHash": filter_hash,
        }
        raw = canonical_json_bytes(payload)
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(value, filter_hash):
        if not value:
            return None
        try:
            padding = "=" * (-len(value) % 4)
            payload = json.loads(base64.urlsafe_b64decode(value + padding))
            if set(payload) != {"version", "occurredAt", "sourceRank", "eventId", "filterHash"}:
                raise ValueError
            occurred = _parse_time(payload["occurredAt"])
            if (payload["version"] != 1 or occurred is None
                    or type(payload["sourceRank"]) is not int
                    or not isinstance(payload["eventId"], str)
                    or not isinstance(payload["filterHash"], str)):
                raise ValueError
        except (ValueError, TypeError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError):
            raise HTTPException(400, "INVALID_SYSTEM_LOG_CURSOR")
        if payload["filterHash"] != filter_hash:
            raise HTTPException(400, "SYSTEM_LOG_CURSOR_FILTER_MISMATCH")
        return occurred, payload["sourceRank"], payload["eventId"]

    def _sql_time(self, value):
        value = _utc(value)
        if value is not None and self.db.bind.dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def _time_bounds(self, query, expression, filters):
        if filters.get("from_time") is not None:
            query = query.where(expression >= self._sql_time(filters["from_time"]))
        if filters.get("to_time") is not None:
            query = query.where(expression <= self._sql_time(filters["to_time"]))
        return query

    @staticmethod
    def _passes(event, filters, cursor_key=None):
        view = filters["view"]
        if view == "errors" and event["level"] != "ERROR":
            return False
        if view == "needs_review" and event["level"] != "REVIEW_REQUIRED":
            return False
        if view == "attention" and event["level"] not in {"ERROR", "REVIEW_REQUIRED"}:
            return False
        direct = {
            "level": event["level"],
            "service": event["service"],
            "provider": event["provider"],
            "error_code": event["errorCode"],
            "failure_class": event["failureClass"],
        }
        for key, actual in direct.items():
            if filters.get(key) is not None and filters[key] != actual:
                return False
        scope = event["scope"]
        for key, public in (
            ("novel_id", "novelId"), ("chapter_id", "chapterId"),
            ("shot_id", "shotId"), ("task_id", "taskId"),
        ):
            if filters.get(key) is not None and filters[key] != scope.get(public):
                return False
        if filters.get("from_time") is not None and event["_sortTime"] < _utc(filters["from_time"]):
            return False
        if filters.get("to_time") is not None and event["_sortTime"] > _utc(filters["to_time"]):
            return False
        if cursor_key is not None:
            key = (event["_sortTime"], event["sourceRank"], event["eventId"])
            if key >= cursor_key:
                return False
        return True

    def _observation_events(self, filters, scan_limit):
        model = ExternalFailureObservation
        columns = (
            model.id, model.occurred_at, model.level, model.service, model.provider,
            model.stage, model.operation, model.error_code, model.failure_class,
            model.novel_id, model.chapter_id, model.shot_id, model.shot_index,
            model.clip_index, model.frame_index, model.reference_index, model.task_id,
            model.attempt_kind, model.attempt_id, model.attempt_no, model.retry_no,
            model.http_status, model.submission_state, model.cid, model.diagnostic_json,
        )
        query = select(*columns)
        for key, column in (
            ("level", model.level), ("service", model.service), ("provider", model.provider),
            ("novel_id", model.novel_id), ("chapter_id", model.chapter_id),
            ("shot_id", model.shot_id), ("task_id", model.task_id),
            ("error_code", model.error_code), ("failure_class", model.failure_class),
        ):
            if filters.get(key) is not None:
                query = query.where(column == filters[key])
        query = self._time_bounds(query, model.occurred_at, filters)
        query = query.order_by(model.occurred_at.desc(), model.id.desc())
        if scan_limit is not None:
            query = query.limit(scan_limit)
        events = []
        for row in self.db.execute(query).all():
            compact = _safe_compact(row.diagnostic_json)
            if compact is None or compact.get("diagnostic_id") != row.id:
                continue
            scope = compact.get("scope") or {}
            call = compact.get("external_call") or {}
            submission = compact.get("submission") or {}
            expected = {
                "level": compact.get("level"), "service": compact.get("service"),
                "provider": compact.get("provider"), "stage": compact.get("stage"),
                "operation": compact.get("operation"), "error_code": compact.get("error_code"),
                "failure_class": compact.get("failure_class"), "novel_id": scope.get("book_id"),
                "chapter_id": scope.get("chapter_id"), "shot_id": scope.get("shot_id"),
                "shot_index": scope.get("shot_index"), "clip_index": scope.get("clip_index"),
                "frame_index": scope.get("frame_index"), "reference_index": scope.get("reference_index"),
                "task_id": scope.get("task_id"), "attempt_kind": scope.get("attempt_kind"),
                "attempt_id": scope.get("attempt_id"), "attempt_no": scope.get("attempt_no"),
                "retry_no": scope.get("retry_no"), "http_status": call.get("http_status"),
                "submission_state": submission.get("state"), "cid": submission.get("cid"),
            }
            if any(getattr(row, key) != value for key, value in expected.items()):
                continue
            level = row.level if row.level in {"ERROR", "WARNING", "INFO", "REVIEW_REQUIRED"} else "ERROR"
            service = _label(row.service, "external")
            provider = _label(row.provider) if row.provider is not None else None
            stage = _operation(row.stage, "EXTERNAL")
            operation = _operation(row.operation, "EXTERNAL_CALL")
            error_code = row.error_code if _ERROR_CODE.fullmatch(row.error_code or "") else "EXTERNAL_FAILURE"
            failure_class = row.failure_class if row.failure_class in FAILURE_CLASSES else "UNKNOWN"
            submission_quality = (
                "NOT_SUBMITTED_PROVEN"
                if (row.submission_state == "NOT_SUBMITTED" and row.cid is None
                    and submission.get("queue_called") is False
                    and submission.get("submitted") is False
                    and submission.get("state") == "NOT_SUBMITTED"
                    and submission.get("cid") is None)
                else "UNKNOWN_SUBMISSION_STATE"
            )
            events.append(_event(
                event_id=f"observation:{row.id}", source="external_failure_observation",
                occurred_at=_utc(row.occurred_at), level=level, service=service,
                provider=provider, stage=stage, operation=operation,
                error_code=error_code, failure_class=failure_class,
                summary=f"{error_code}: {failure_class}",
                scope=_scope(
                    novel_id=row.novel_id, chapter_id=row.chapter_id, shot_id=row.shot_id,
                    shot_index=row.shot_index, clip_index=row.clip_index, frame_index=row.frame_index,
                    reference_index=row.reference_index, task_id=row.task_id,
                    attempt_kind=row.attempt_kind, attempt_id=row.attempt_id,
                    attempt_no=row.attempt_no, retry_no=row.retry_no,
                ),
                qualities=_qualities("STRUCTURED_V1", submission_quality),
                submission={"state": row.submission_state, "cid": row.cid},
                detail=None,
            ))
        return events

    def _task_diagnostic_events(self, filters, scan_limit, observed_ids):
        if self.db.bind.dialect.name != "sqlite":
            return []
        task_time = "COALESCE(t.completed_at, t.updated_at, t.created_at)"
        clauses = ["t.status IN ('completed','failed','cancelled')"]
        params = {}
        statement = text(f"""
            SELECT t.id AS task_id, t.status, t.type, t.novel_id, t.chapter_id, t.shot_id,
                   t.completed_at, t.updated_at, t.created_at,
                   json_extract(clip.value, '$.external_failure') AS diagnostic_json
            FROM tasks AS t
            JOIN json_each(
                CASE WHEN json_valid(t.metadata_json)
                     THEN CASE WHEN json_type(t.metadata_json, '$.video_run.clips') = 'object'
                               THEN json_extract(t.metadata_json, '$.video_run.clips')
                               ELSE '{{}}' END
                     ELSE '{{}}' END
            ) AS clip
            WHERE {' AND '.join(clauses)}
              AND json_type(
                  CASE WHEN json_valid(clip.value) THEN clip.value ELSE '{{}}' END,
                  '$.external_failure'
              ) = 'object'
            ORDER BY {task_time} DESC, t.id DESC
        """)
        events = []
        for row in self.db.execute(statement, params).mappings():
            compact = _safe_compact(row["diagnostic_json"])
            if (compact is None or compact["diagnostic_id"] in observed_ids
                    or not _compact_belongs_to_task(compact, row)):
                continue
            domain = {
                "taskId": row["task_id"], "taskStatus": row["status"],
                "taskType": row["type"], "novelId": row["novel_id"],
                "chapterId": row["chapter_id"], "shotId": row["shot_id"],
            }
            fallback = row["completed_at"] or row["updated_at"] or row["created_at"]
            event = _diagnostic_event(
                compact, source="task_compact_diagnostic",
                event_id=f"task-diagnostic:{row['task_id']}:{compact['diagnostic_id']}",
                fallback_time=fallback, domain=domain,
            )
            if event is not None:
                events.append(event)
        return events

    def _task_events(self, filters, scan_limit):
        if filters.get("service") not in (None, "task") or filters.get("provider") is not None:
            return []
        task_time = func.coalesce(Task.completed_at, Task.updated_at, Task.created_at)
        query = select(
            Task.id, Task.type, Task.status, Task.error_message, Task.novel_id,
            Task.chapter_id, Task.shot_id, Task.attempt, Task.comfyui_prompt_id,
            Task.completed_at, Task.updated_at, Task.created_at,
        ).where(Task.status.in_(TERMINAL_TASK_STATUSES))
        for key, column in (
            ("novel_id", Task.novel_id), ("chapter_id", Task.chapter_id),
            ("shot_id", Task.shot_id), ("task_id", Task.id),
        ):
            if filters.get(key) is not None:
                query = query.where(column == filters[key])
        query = self._time_bounds(query, task_time, filters)
        query = query.order_by(task_time.desc(), Task.id.desc())
        if scan_limit is not None:
            query = query.limit(scan_limit)
        events = []
        for row in self.db.execute(query).all():
            level = "ERROR" if row.status == "failed" else "WARNING" if row.status == "cancelled" else "INFO"
            match = _ERROR_CODE.match(row.error_message or "")
            code = match.group(1) if match else (
                "TASK_FAILED" if row.status == "failed" else
                "TASK_CANCELLED" if row.status == "cancelled" else "TASK_COMPLETED"
            )
            occurred = row.completed_at or row.updated_at or row.created_at
            if occurred is None:
                continue
            submission_quality = "UNKNOWN_SUBMISSION_STATE"
            operation = _operation(row.type, "TASK")
            events.append(_event(
                event_id=f"task:{row.id}:terminal", source="task_terminal", occurred_at=_utc(occurred),
                level=level, service="task", provider=None, stage="TASK", operation=operation,
                error_code=code, failure_class="UNKNOWN" if level == "ERROR" else None,
                summary=f"Task {operation} {row.status} ({code})",
                scope=_scope(
                    novel_id=row.novel_id, chapter_id=row.chapter_id, shot_id=row.shot_id,
                    task_id=row.id, attempt_no=row.attempt,
                ),
                qualities=_qualities(
                    "LEGACY_SUMMARY_ONLY",
                    "TIMESTAMP_FALLBACK" if row.completed_at is None else None,
                    submission_quality,
                ),
                submission={"state": "UNKNOWN", "cid": row.comfyui_prompt_id},
                detail={"domainState": {
                    "taskId": row.id, "taskType": row.type, "taskStatus": row.status,
                    "attemptNo": row.attempt,
                }},
            ))
        return events

    def _llm_events(self, filters, scan_limit):
        if filters.get("service") not in (None, "llm"):
            return []
        query = select(
            LLMLog.id, LLMLog.created_at, LLMLog.provider, LLMLog.model,
            LLMLog.status, LLMLog.task_type, LLMLog.novel_id, LLMLog.chapter_id,
            LLMLog.duration,
        )
        for key, column in (
            ("provider", LLMLog.provider), ("novel_id", LLMLog.novel_id),
            ("chapter_id", LLMLog.chapter_id),
        ):
            if filters.get(key) is not None:
                query = query.where(column == filters[key])
        if filters.get("shot_id") is not None or filters.get("task_id") is not None:
            return []
        query = self._time_bounds(query, LLMLog.created_at, filters)
        query = query.order_by(LLMLog.created_at.desc(), LLMLog.id.desc())
        if scan_limit is not None:
            query = query.limit(scan_limit)
        events = []
        for row in self.db.execute(query).all():
            if row.created_at is None:
                continue
            status = row.status or "pending"
            level = "ERROR" if status == "error" else "INFO"
            code = "LLM_CALL_FAILED" if status == "error" else "LLM_CALL_COMPLETED" if status == "success" else "LLM_CALL_STARTED"
            provider = _label(row.provider, "unknown")
            model = _label(row.model, "unknown")
            operation = _operation(row.task_type, "LLM_CALL")
            events.append(_event(
                event_id=f"llm:{row.id}", source="llm_lifecycle", occurred_at=_utc(row.created_at),
                level=level, service="llm", provider=provider, stage="LLM", operation=operation,
                error_code=code, failure_class="UNKNOWN" if status == "error" else None,
                summary=f"LLM {provider}/{model} {status}",
                scope=_scope(novel_id=row.novel_id, chapter_id=row.chapter_id),
                qualities=_qualities(
                    "LEGACY_SUMMARY_ONLY" if status == "error" else None,
                    "TIMESTAMP_FALLBACK" if status in {"success", "error"} else None,
                ),
                detail={"llm": {
                    "logId": row.id, "provider": provider, "model": model,
                    "status": status, "taskType": row.task_type, "durationSeconds": row.duration,
                }},
            ))
        return events

    def _review_events(self, filters, scan_limit):
        if self.db.bind.dialect.name != "sqlite":
            return []
        if filters.get("service") not in (None, "review") or filters.get("provider") is not None:
            return []
        task_time = "COALESCE(t.updated_at, t.completed_at, t.created_at)"
        clauses = ["1 = 1"]
        params = {}
        for key, column in (
            ("novel_id", "t.novel_id"), ("chapter_id", "t.chapter_id"),
            ("shot_id", "t.shot_id"), ("task_id", "t.id"),
        ):
            if filters.get(key) is not None:
                clauses.append(f"{column} = :{key}")
                params[key] = filters[key]
        statement = text(f"""
            SELECT t.id AS task_id, t.novel_id, t.chapter_id, t.shot_id,
                   t.updated_at, t.completed_at, t.created_at, finding.value AS finding_json
            FROM tasks AS t
            JOIN json_each(
                CASE WHEN json_valid(t.metadata_json)
                     THEN CASE WHEN json_type(t.metadata_json, '$.review_findings.items') = 'array'
                               THEN json_extract(t.metadata_json, '$.review_findings.items')
                               ELSE '[]' END
                     ELSE '[]' END
            ) AS finding
            WHERE {' AND '.join(clauses)}
              AND json_type(
                  CASE WHEN json_valid(finding.value) THEN finding.value ELSE '{{}}' END
              ) = 'object'
            ORDER BY {task_time} DESC, t.id DESC
        """)
        events = []
        for row in self.db.execute(statement, params).mappings():
            try:
                finding = json.loads(row["finding_json"])
            except (TypeError, ValueError):
                continue
            evidence = finding.get("evidence")
            if (not _REVIEW_ID.fullmatch(str(finding.get("id") or ""))
                    or finding.get("severity") != "REVIEW_REQUIRED"
                    or finding.get("code") != _REVIEW_CODE
                    or finding.get("message") != _REVIEW_MESSAGE
                    or finding.get("status") != "OPEN"
                    or finding.get("fallback_action") != _REVIEW_ACTION
                    or finding.get("fallback_outcome") not in {"PENDING", "SUCCEEDED", "FAILED"}
                    or finding.get("task_id") != row["task_id"]
                    or finding.get("book_id") != row["novel_id"]
                    or finding.get("chapter_id") != row["chapter_id"]
                    or finding.get("shot_id") != row["shot_id"]
                    or not isinstance(evidence, dict)
                    or set(evidence) != {
                        "attempt_execution_path", "first_failed_llm_log_id", "first_response_sha256",
                        "frozen_input_sha256", "manifest_sha256", "rsa_hash", "template_sha256",
                    }
                    or evidence.get("attempt_execution_path") != "RsaImageAttempt.execution.prompt_attempts[0]"
                    or not _PUBLIC_ID.fullmatch(str(evidence.get("first_failed_llm_log_id") or ""))
                    or any(not _HASH.fullmatch(str(evidence.get(key) or "")) for key in (
                        "first_response_sha256", "frozen_input_sha256", "manifest_sha256",
                        "rsa_hash", "template_sha256",
                    ))):
                continue
            occurred = row["updated_at"] or row["completed_at"] or row["created_at"]
            if occurred is None:
                continue
            scope = _scope(
                novel_id=finding.get("book_id"), chapter_id=finding.get("chapter_id"),
                shot_id=finding.get("shot_id"), shot_index=finding.get("shot_index"),
                clip_index=finding.get("clip_index"), frame_index=finding.get("frame_index"),
                task_id=finding.get("task_id"), attempt_id=row["task_id"],
            )
            public_evidence = {
                public: evidence.get(saved) for public, saved in (
                    ("attemptExecutionPath", "attempt_execution_path"),
                    ("firstFailedLlmLogId", "first_failed_llm_log_id"),
                    ("firstResponseSha256", "first_response_sha256"),
                    ("frozenInputSha256", "frozen_input_sha256"),
                    ("manifestSha256", "manifest_sha256"),
                    ("rsaHash", "rsa_hash"), ("templateSha256", "template_sha256"),
                )
            }
            events.append(_event(
                event_id=f"review:{finding['id']}", source="review_finding", occurred_at=_utc(occurred),
                level="REVIEW_REQUIRED", service="review", provider=None, stage="KEYFRAME",
                operation="REVIEW_FINDING", error_code=_REVIEW_CODE, failure_class=None,
                summary=_REVIEW_MESSAGE, scope=scope, qualities=_qualities("TIMESTAMP_FALLBACK"),
                detail={"reviewFinding": {
                    "findingId": finding["id"], "code": _REVIEW_CODE,
                    "message": _REVIEW_MESSAGE, "status": "OPEN",
                    "fallbackAction": _REVIEW_ACTION,
                    "fallbackOutcome": finding.get("fallback_outcome"),
                    "evidence": public_evidence,
                }},
            ))
        return events

    def list(self, **filters):
        if filters.get("view") not in VIEWS:
            raise HTTPException(422, "INVALID_SYSTEM_LOG_VIEW")
        filters = dict(filters)
        for key in ("from_time", "to_time"):
            if filters.get(key) is not None:
                normalized = _utc(filters[key])
                if normalized is None:
                    raise HTTPException(422, "INVALID_SYSTEM_LOG_TIME_BOUND")
                filters[key] = normalized
        if (filters.get("from_time") is not None and filters.get("to_time") is not None
                and filters["from_time"] > filters["to_time"]):
            raise HTTPException(422, "INVALID_SYSTEM_LOG_TIME_RANGE")
        filter_hash = self._filter_hash(filters)
        cursor_key = self._decode_cursor(filters.get("cursor"), filter_hash)
        limit = filters["limit"]
        scan_limit = None

        observed = self.db.execute(select(
            ExternalFailureObservation.id, ExternalFailureObservation.task_id
        )).all()
        observed_ids = {row.id for row in observed}
        observation_events = self._observation_events(filters, scan_limit)
        diagnostic_events = self._task_diagnostic_events(filters, scan_limit, observed_ids)
        events = observation_events + diagnostic_events
        events += self._review_events(filters, scan_limit)
        events += self._task_events(filters, scan_limit)
        events += self._llm_events(filters, scan_limit)
        events = [event for event in events if self._passes(event, filters, cursor_key)]
        events.sort(key=lambda event: (event["_sortTime"], event["sourceRank"], event["eventId"]), reverse=True)
        page = events[:limit]
        has_more = len(events) > limit
        next_cursor = self._encode_cursor(page[-1], filter_hash) if has_more and page else None
        return {
            "items": [_public(event) for event in page],
            "nextCursor": next_cursor,
            "hasMore": has_more,
        }

    def _task_domain_state(self, task_id):
        if not task_id:
            return None
        row = self.db.execute(select(
            Task.id, Task.type, Task.status, Task.novel_id, Task.chapter_id,
            Task.shot_id, Task.attempt, Task.completed_at,
        ).where(Task.id == task_id)).first()
        if row is None:
            return {"taskId": task_id, "availability": "MISSING"}
        return {
            "taskId": row.id, "taskType": row.type, "taskStatus": row.status,
            "novelId": row.novel_id, "chapterId": row.chapter_id, "shotId": row.shot_id,
            "attemptNo": row.attempt, "completedAt": _iso(row.completed_at) if row.completed_at else None,
        }

    def _observation_detail(self, diagnostic_id):
        row = self.db.execute(select(ExternalFailureObservation).where(
            ExternalFailureObservation.id == diagnostic_id
        )).scalar_one_or_none()
        if row is None:
            return None
        compact = _safe_compact(row.diagnostic_json)
        if compact is None:
            raise HTTPException(409, "CORRUPT_SYSTEM_LOG_DIAGNOSTIC")
        event = _diagnostic_event(
            compact, source="external_failure_observation",
            event_id=f"observation:{row.id}", fallback_time=row.occurred_at,
            domain=self._task_domain_state(row.task_id),
        )
        if event is None:
            return None
        event["_sortTime"] = _utc(row.occurred_at)
        event["occurredAt"] = _iso(row.occurred_at)
        return event

    def _task_diagnostic_detail(self, event_id):
        try:
            _, task_id, diagnostic_id = event_id.split(":", 2)
        except ValueError:
            return None
        if not _DIAGNOSTIC_ID.fullmatch(diagnostic_id) or self.db.bind.dialect.name != "sqlite":
            return None
        statement = text("""
            SELECT t.id AS task_id, t.status, t.type, t.novel_id, t.chapter_id, t.shot_id,
                   t.completed_at, t.updated_at, t.created_at,
                   json_extract(clip.value, '$.external_failure') AS diagnostic_json
            FROM tasks AS t
            JOIN json_each(
                CASE WHEN json_valid(t.metadata_json)
                     THEN CASE WHEN json_type(t.metadata_json, '$.video_run.clips') = 'object'
                               THEN json_extract(t.metadata_json, '$.video_run.clips')
                               ELSE '{}' END
                     ELSE '{}' END
            ) AS clip
            WHERE t.id = :task_id
              AND json_extract(
                  CASE WHEN json_valid(clip.value) THEN clip.value ELSE '{}' END,
                  '$.external_failure.diagnostic_id'
              ) = :diagnostic_id
            LIMIT 1
        """)
        row = self.db.execute(statement, {"task_id": task_id, "diagnostic_id": diagnostic_id}).mappings().first()
        if row is None:
            return None
        compact = _safe_compact(row["diagnostic_json"])
        if compact is None:
            raise HTTPException(409, "CORRUPT_SYSTEM_LOG_DIAGNOSTIC")
        if not _compact_belongs_to_task(compact, row):
            return None
        fallback = row["completed_at"] or row["updated_at"] or row["created_at"]
        return _diagnostic_event(
            compact, source="task_compact_diagnostic", event_id=event_id,
            fallback_time=fallback, domain=self._task_domain_state(task_id),
        )

    def _task_detail(self, event_id):
        match = re.fullmatch(r"task:([^:]+):terminal", event_id)
        if not match:
            return None
        filters = {
            "view": "all", "task_id": match.group(1), "limit": 2, "cursor": None,
            "level": None, "service": "task", "provider": None, "novel_id": None,
            "chapter_id": None, "shot_id": None, "error_code": None,
            "failure_class": None, "from_time": None, "to_time": None,
        }
        rows = self._task_events(filters, None)
        return next((event for event in rows if event["eventId"] == event_id), None)

    def _llm_detail(self, event_id):
        if not event_id.startswith("llm:"):
            return None
        query_id = event_id.removeprefix("llm:")
        row = self.db.execute(select(
            LLMLog.id, LLMLog.created_at, LLMLog.provider, LLMLog.model,
            LLMLog.status, LLMLog.task_type, LLMLog.novel_id, LLMLog.chapter_id,
            LLMLog.duration,
        ).where(LLMLog.id == query_id)).first()
        if row is None or row.created_at is None:
            return None
        provider, model = _label(row.provider, "unknown"), _label(row.model, "unknown")
        status = row.status or "pending"
        level = "ERROR" if status == "error" else "INFO"
        code = "LLM_CALL_FAILED" if status == "error" else "LLM_CALL_COMPLETED" if status == "success" else "LLM_CALL_STARTED"
        return _event(
            event_id=event_id, source="llm_lifecycle", occurred_at=_utc(row.created_at),
            level=level, service="llm", provider=provider, stage="LLM",
            operation=_operation(row.task_type, "LLM_CALL"), error_code=code,
            failure_class="UNKNOWN" if status == "error" else None,
            summary=f"LLM {provider}/{model} {status}",
            scope=_scope(novel_id=row.novel_id, chapter_id=row.chapter_id),
            qualities=_qualities("LEGACY_SUMMARY_ONLY" if status == "error" else None, "TIMESTAMP_FALLBACK"),
            detail={"llm": {
                "logId": row.id, "provider": provider, "model": model,
                "status": status, "taskType": row.task_type, "durationSeconds": row.duration,
            }},
        )

    def _review_detail(self, event_id):
        if not event_id.startswith("review:"):
            return None
        filters = {
            "view": "all", "limit": 2000, "cursor": None, "service": "review",
            "provider": None, "novel_id": None, "chapter_id": None, "shot_id": None,
            "task_id": None, "from_time": None, "to_time": None,
        }
        return next((event for event in self._review_events(filters, 2000) if event["eventId"] == event_id), None)

    def detail(self, event_id):
        if event_id.startswith("observation:"):
            event = self._observation_detail(event_id.removeprefix("observation:"))
        elif event_id.startswith("task-diagnostic:"):
            event = self._task_diagnostic_detail(event_id)
        elif event_id.startswith("task:"):
            event = self._task_detail(event_id)
        elif event_id.startswith("llm:"):
            event = self._llm_detail(event_id)
        elif event_id.startswith("review:"):
            event = self._review_detail(event_id)
        else:
            event = None
        if event is None:
            raise HTTPException(404, "SYSTEM_LOG_EVENT_NOT_FOUND")
        return _public(event, detail=True)

    def filters(self):
        filters = {
            "view": "all", "level": None, "service": None, "provider": None,
            "novel_id": None, "chapter_id": None, "shot_id": None, "task_id": None,
            "error_code": None, "failure_class": None, "from_time": None, "to_time": None,
            "cursor": None, "limit": 100,
        }
        observed = self.db.execute(select(
            ExternalFailureObservation.id, ExternalFailureObservation.task_id
        )).all()
        events = self._observation_events(filters, None)
        events += self._task_diagnostic_events(filters, None, {row.id for row in observed})
        events += self._review_events(filters, None)
        events += self._task_events(filters, None)
        events += self._llm_events(filters, None)

        def values(items):
            return sorted({item for item in items if isinstance(item, str) and item})

        return {
            "views": sorted(VIEWS),
            "levels": values([event["level"] for event in events]),
            "services": values([event["service"] for event in events]),
            "providers": values([event["provider"] for event in events]),
            "errorCodes": values([event["errorCode"] for event in events]),
            "failureClasses": values([event["failureClass"] for event in events]),
            "novelIds": values([event["scope"]["novelId"] for event in events]),
            "chapterIds": values([event["scope"]["chapterId"] for event in events]),
            "shotIds": values([event["scope"]["shotId"] for event in events]),
            "taskIds": values([event["scope"]["taskId"] for event in events]),
        }


__all__ = ["SystemLogService"]
