from datetime import datetime, timedelta, timezone
import hashlib
import json
import socket

import pytest
from sqlalchemy import event, text

from app.models.llm_log import LLMLog
from app.models.task import Task
from app.services.external_failure_observation_service import append_external_failure_observation
from test_external_failure_observation import diagnostic


NOW = datetime(2026, 9, 16, 9, 30, tzinfo=timezone.utc)
CANARIES = (
    "STAGE_B_SECRET_TOKEN_7719",
    "/private/stage-b/secret/workflow.json",
    "STAGE_B_RAW_RESPONSE_8821",
    "STAGE_B_PROMPT_9932",
)


def review_finding(task_id="task-review"):
    hashes = {key: hashlib.sha256(key.encode()).hexdigest() for key in (
        "response", "input", "manifest", "rsa", "template",
    )}
    return {
        "id": "review-" + "a" * 32,
        "book_id": "novel-1", "chapter_id": "chapter-1", "shot_id": "shot-1",
        "shot_index": 1, "clip_index": None, "frame_index": 0, "task_id": task_id,
        "severity": "REVIEW_REQUIRED", "code": "UNBOUND_ASSET_REFERENCE",
        "message": "Fresh keyframe prompt contained an asset reference not bound to the frozen manifest.",
        "fallback_action": "RETRY_PROMPT_ONCE_SAME_FROZEN_INPUTS",
        "status": "OPEN", "fallback_outcome": "PENDING",
        "evidence": {
            "attempt_execution_path": "RsaImageAttempt.execution.prompt_attempts[0]",
            "first_failed_llm_log_id": "llm-review",
            "first_response_sha256": hashes["response"],
            "frozen_input_sha256": hashes["input"],
            "manifest_sha256": hashes["manifest"],
            "rsa_hash": hashes["rsa"],
            "template_sha256": hashes["template"],
        },
    }


@pytest.fixture
def system_log_records(db_session):
    naive = NOW.replace(tzinfo=None)
    observations = []
    for seed, task_id in (("obs-a", "task-obs-a"), ("obs-b", "task-obs-b")):
        value = diagnostic(seed, when=NOW, task_id=task_id)
        value["external_call"]["exception_message"] = (
            f"Authorization: Token {CANARIES[0]} at {CANARIES[1]}"
        )
        append_external_failure_observation(db_session, value, recorded_at=NOW)
        observations.append(value)
        db_session.add(Task(
            id=task_id, type="shot_video", status="failed", name=task_id,
            novel_id="novel-1", chapter_id="chapter-1", shot_id="shot-1",
            error_message="VALIDATED_REFERENCE_UPLOAD_FAILED", completed_at=naive,
        ))

    fallback = diagnostic("fallback", when=NOW, task_id="task-fallback")
    db_session.add(Task(
        id="task-fallback", type="shot_video", status="failed", name="fallback",
        novel_id="novel-1", chapter_id="chapter-1", shot_id="shot-1",
        error_message="VALIDATED_REFERENCE_UPLOAD_FAILED",
        completed_at=(NOW + timedelta(hours=2)).replace(tzinfo=None),
        metadata_json=json.dumps({"video_run": {"clips": {"1": {"external_failure": fallback}}}}),
    ))
    db_session.add(Task(
        id="task-legacy", type="shot_video", status="failed", name="historic Shot2",
        novel_id="novel-1", chapter_id="chapter-1", shot_id="shot-2",
        error_message=f"HISTORIC_UPLOAD_FAILED: {CANARIES[1]} {CANARIES[0]}",
        completed_at=naive,
    ))
    db_session.add(Task(
        id="task-completed", type="shot_video", status="completed", name="completed",
        novel_id="novel-1", chapter_id="chapter-1", shot_id="shot-3", completed_at=naive,
    ))
    db_session.add(Task(
        id="task-corrupt", type="shot_video", status="failed", name="corrupt",
        novel_id="novel-1", chapter_id="chapter-1", shot_id="shot-corrupt",
        error_message=f"CORRUPT_METADATA: {CANARIES[0]}", metadata_json="{not-json",
        completed_at=naive,
    ))
    db_session.add(Task(
        id="task-wrong-json-shape", type="shot_video", status="failed", name="wrong shape",
        novel_id="novel-1", chapter_id="chapter-1", shot_id="shot-corrupt",
        error_message="WRONG_JSON_SHAPE", metadata_json=json.dumps({
            "video_run": {"clips": "not-a-clip-map"},
            "review_findings": {"version": 1, "items": "not-a-finding-list"},
        }),
        completed_at=naive,
    ))
    finding = review_finding()
    db_session.add(Task(
        id="task-review", type="shot_image", status="running", name="review",
        novel_id="novel-1", chapter_id="chapter-1", shot_id="shot-1",
        metadata_json=json.dumps({"review_findings": {"version": 1, "items": [finding]}}),
        created_at=naive, updated_at=naive,
    ))
    db_session.add(LLMLog(
        id="llm-error", provider="openai", model="test-model", status="error",
        task_type="keyframe_image_prompt", novel_id="novel-1", chapter_id="chapter-1",
        system_prompt=CANARIES[3], user_prompt=CANARIES[3], response=CANARIES[2],
        request_info=json.dumps({"authorization": CANARIES[0]}),
        error_message=f"provider failed {CANARIES[0]}", created_at=naive,
    ))
    db_session.commit()
    return {
        "observations": observations,
        "fallback": fallback,
        "review": finding,
    }


def _items(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


@pytest.mark.CANONICAL_DB
def test_system_log_views_filters_and_historical_unknown(client, system_log_records):
    attention = _items(client.get("/api/system-logs/"))
    assert attention and {item["level"] for item in attention} <= {"ERROR", "REVIEW_REQUIRED"}
    errors = _items(client.get("/api/system-logs/", params={"view": "errors"}))
    assert errors and {item["level"] for item in errors} == {"ERROR"}
    review = _items(client.get("/api/system-logs/", params={"view": "needs_review"}))
    assert [item["source"] for item in review] == ["review_finding"]
    all_items = _items(client.get("/api/system-logs/", params={"view": "all"}))
    assert any(item["level"] == "INFO" for item in all_items)

    checks = {
        "level": "ERROR", "service": "comfyui", "provider": "comfyui",
        "novel_id": "novel-1", "chapter_id": "chapter-1", "shot_id": "shot-1",
        "task_id": "task-fallback", "error_code": "VALIDATED_REFERENCE_UPLOAD_FAILED",
        "failure_class": "HTTP_ERROR",
    }
    public = {
        "level": lambda item: item["level"], "service": lambda item: item["service"],
        "provider": lambda item: item["provider"], "novel_id": lambda item: item["scope"]["novelId"],
        "chapter_id": lambda item: item["scope"]["chapterId"], "shot_id": lambda item: item["scope"]["shotId"],
        "task_id": lambda item: item["scope"]["taskId"], "error_code": lambda item: item["errorCode"],
        "failure_class": lambda item: item["failureClass"],
    }
    for key, value in checks.items():
        filtered = _items(client.get("/api/system-logs/", params={"view": "all", key: value}))
        assert filtered and all(public[key](item) == value for item in filtered)
    bounded = _items(client.get("/api/system-logs/", params={
        "view": "all", "from": (NOW - timedelta(seconds=1)).astimezone(timezone(timedelta(hours=8))).isoformat(),
        "to": (NOW + timedelta(seconds=1)).astimezone(timezone(timedelta(hours=8))).isoformat(),
    }))
    assert any(item["source"] == "task_compact_diagnostic" and item["scope"]["taskId"] == "task-fallback" for item in bounded)

    task_events = _items(client.get("/api/system-logs/", params={"view": "all", "service": "task"}))
    assert any(item["scope"]["taskId"] == "task-obs-a" for item in task_events)

    historic = next(item for item in all_items if item["scope"]["taskId"] == "task-legacy")
    assert historic["failureClass"] == "UNKNOWN"
    assert "LEGACY_SUMMARY_ONLY" in historic["diagnosticQualityFlags"]
    assert "UNKNOWN_SUBMISSION_STATE" in historic["diagnosticQualityFlags"]
    assert "NOT_SUBMITTED_PROVEN" not in historic["diagnosticQualityFlags"]

    filters = client.get("/api/system-logs/filters")
    assert filters.status_code == 200
    data = filters.json()["data"]
    assert {"all", "errors", "needs_review", "attention"} == set(data["views"])
    assert {"comfyui", "llm", "review", "task"} <= set(data["services"])
    assert "HTTP_ERROR" in data["failureClasses"] and "openai" in data["providers"]
    assert "HISTORIC_UPLOAD_FAILED" in data["errorCodes"]
    assert "task-review" in data["taskIds"]


@pytest.mark.CANONICAL_DB
def test_system_log_cursor_is_stable_and_bound_to_filters(client, system_log_records):
    expected = _items(client.get("/api/system-logs/", params={"view": "all", "limit": 100}))
    seen, cursor = [], None
    while True:
        params = {"view": "all", "limit": 1}
        if cursor:
            params["cursor"] = cursor
        response = client.get("/api/system-logs/", params=params)
        assert response.status_code == 200
        data = response.json()["data"]
        seen.extend(data["items"])
        cursor = data["nextCursor"]
        if not cursor:
            break
        assert len(seen) <= len(expected)
    assert [item["eventId"] for item in seen] == [item["eventId"] for item in expected]
    assert len({item["eventId"] for item in seen}) == len(seen)

    first = client.get("/api/system-logs/", params={"view": "all", "limit": 2}).json()["data"]
    assert first["nextCursor"]
    mismatch = client.get("/api/system-logs/", params={
        "view": "errors", "limit": 2, "cursor": first["nextCursor"],
    })
    assert mismatch.status_code == 400
    assert mismatch.json()["detail"] == "SYSTEM_LOG_CURSOR_FILTER_MISMATCH"
    assert client.get("/api/system-logs/", params={"cursor": "not-a-cursor"}).status_code == 400


@pytest.mark.CANONICAL_DB
def test_compact_fallback_scope_must_match_its_owning_task(client, db_session, system_log_records):
    foreign = diagnostic("foreign-scope", when=NOW, task_id="task-foreign")
    foreign["scope"].update(
        book_id="novel-foreign", chapter_id="chapter-foreign", shot_id="shot-foreign",
    )
    db_session.add(Task(
        id="task-container", type="shot_video", status="failed", name="container",
        novel_id="novel-1", chapter_id="chapter-1", shot_id="shot-1",
        error_message="VALIDATED_REFERENCE_UPLOAD_FAILED", completed_at=NOW.replace(tzinfo=None),
        metadata_json=json.dumps({"video_run": {"clips": {"1": {"external_failure": foreign}}}}),
    ))
    db_session.commit()

    foreign_list = _items(client.get("/api/system-logs/", params={
        "view": "all", "task_id": "task-foreign",
    }))
    assert foreign_list == []
    all_items = _items(client.get("/api/system-logs/", params={"view": "all", "limit": 100}))
    assert not any(
        item["source"] == "task_compact_diagnostic"
        and item["scope"]["taskId"] == "task-foreign"
        for item in all_items
    )
    event_id = f"task-diagnostic:task-container:{foreign['diagnostic_id']}"
    assert client.get(f"/api/system-logs/{event_id}").status_code == 404

    legal = _items(client.get("/api/system-logs/", params={
        "view": "all", "task_id": "task-fallback",
    }))
    fallback = next(item for item in legal if item["source"] == "task_compact_diagnostic")
    assert fallback["scope"] == {
        "novelId": "novel-1", "chapterId": "chapter-1", "shotId": "shot-1",
        "shotIndex": 1, "clipIndex": 1, "frameIndex": None, "referenceIndex": 0,
        "taskId": "task-fallback", "attemptKind": "SHOT_VIDEO",
        "attemptId": "attempt-fallback", "attemptNo": 1, "retryNo": 0,
    }
    assert {"STRUCTURED_V1", "NOT_SUBMITTED_PROVEN"} <= set(fallback["diagnosticQualityFlags"])


@pytest.mark.CANONICAL_DB
def test_review_event_exact_inclusive_timestamp_is_not_lost(client, system_log_records):
    review = _items(client.get("/api/system-logs/", params={"view": "needs_review"}))
    assert len(review) == 1
    event_id, occurred_at = review[0]["eventId"], review[0]["occurredAt"]

    exact = _items(client.get("/api/system-logs/", params={
        "view": "needs_review", "from": occurred_at, "to": occurred_at,
    }))
    assert [item["eventId"] for item in exact] == [event_id]

    offset = datetime.fromisoformat(occurred_at.replace("Z", "+00:00")).astimezone(
        timezone(timedelta(hours=8))
    ).isoformat()
    exact_offset = _items(client.get("/api/system-logs/", params={
        "view": "needs_review", "from": offset, "to": offset,
    }))
    assert [item["eventId"] for item in exact_offset] == [event_id]


@pytest.mark.CANONICAL_DB
def test_system_log_list_and_detail_are_safe_projections(client, db_engine, system_log_records, monkeypatch):
    statements = []

    def read_only(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
        if statement.lstrip().split(None, 1)[0].upper() not in {"SELECT", "WITH", "PRAGMA"}:
            raise AssertionError(f"System Logs GET attempted write SQL: {statement}")

    def no_socket(*_args, **_kwargs):
        raise AssertionError("System Logs GET attempted a network call")

    event.listen(db_engine, "before_cursor_execute", read_only)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    try:
        response = client.get("/api/system-logs/", params={"view": "all", "limit": 100})
        items = _items(response)
        observation = next(item for item in items if item["source"] == "external_failure_observation")
        detail = client.get(f"/api/system-logs/{observation['eventId']}")
        assert detail.status_code == 200
        payload = json.dumps({"list": response.json(), "detail": detail.json()}, ensure_ascii=False)
    finally:
        event.remove(db_engine, "before_cursor_execute", read_only)

    assert statements
    sql = "\n".join(statements).lower()
    for forbidden_column in ("system_prompt", "user_prompt", "workflow_json", "prompt_text", "llm_logs.response"):
        assert forbidden_column not in sql
    for canary in CANARIES:
        assert canary not in payload
    detail_data = detail.json()["data"]["detail"]
    external_call = detail_data["diagnostic"]["externalCall"]
    assert "exceptionStack" not in external_call and "responseExcerpt" not in external_call
    assert detail_data["evidence"]["path"].startswith("evidence-")
    assert "/" not in detail_data["evidence"]["path"] and "\\" not in detail_data["evidence"]["path"]


def _business_snapshot(db):
    tables = (
        "tasks", "shots", "rsa_image_attempts", "rsa_media_artifacts", "llm_logs",
        "external_failure_observations",
    )
    return {
        table: [tuple(row) for row in db.execute(text(f'SELECT * FROM "{table}" ORDER BY 1')).all()]
        for table in tables
    }


@pytest.mark.CANONICAL_DB
def test_system_log_gets_are_read_only_and_write_methods_are_unavailable(client, db_session, system_log_records):
    before = _business_snapshot(db_session)
    listing = client.get("/api/system-logs/", params={"view": "all"})
    assert listing.status_code == 200
    event_id = listing.json()["data"]["items"][0]["eventId"]
    assert client.get("/api/system-logs/filters").status_code == 200
    assert client.get(f"/api/system-logs/{event_id}").status_code == 200
    db_session.expire_all()
    assert _business_snapshot(db_session) == before

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, "/api/system-logs/", json={}).status_code == 405
        assert client.request(method, f"/api/system-logs/{event_id}", json={}).status_code == 405


@pytest.mark.CANONICAL_DB
def test_cursor_traverses_more_than_the_former_prefetch_window(db_session):
    for index in range(205):
        append_external_failure_observation(
            db_session, diagnostic(f"cursor-{index:03d}", when=NOW), recorded_at=NOW,
        )
    db_session.commit()
    from app.services.system_log_service import SystemLogService

    filters = {
        "view": "all", "level": None, "service": None, "provider": None,
        "novel_id": None, "chapter_id": None, "shot_id": None, "task_id": None,
        "error_code": None, "failure_class": None, "from_time": None, "to_time": None,
        "cursor": None, "limit": 100,
    }
    seen = []
    while True:
        page = SystemLogService(db_session).list(**filters)
        seen.extend(item["eventId"] for item in page["items"])
        if not page["nextCursor"]:
            break
        filters["cursor"] = page["nextCursor"]
    assert len(seen) == 205
    assert len(set(seen)) == 205
