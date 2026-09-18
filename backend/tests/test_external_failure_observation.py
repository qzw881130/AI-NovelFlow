import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.models.external_failure_observation import ExternalFailureObservation, UPDATE_TRIGGER_NAME
from app.models.llm_log import LLMLog
from app.models.rsa_media import RsaImageAttempt, RsaMediaArtifact
from app.models.shot import Shot
from app.models.task import Task
from app.services.external_failure_diagnostic import ExternalFailureDiagnostic
from app.services.external_failure_observation_service import (
    ObservationConflict,
    append_external_failure_observation,
    enforce_observation_retention,
    record_external_failure_best_effort,
    run_next_video_task_with_observation,
    safe_observation_diagnostic,
)


def diagnostic(seed="a", *, when=None, task_id=None, message="upload failed"):
    when = when or datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
    digest = __import__("hashlib").sha256(seed.encode()).hexdigest()
    detailed = ExternalFailureDiagnostic.build(
        operation_key={
            "task_id": task_id or f"task-{seed}",
            "attempt_id": f"attempt-{seed}",
            "operation": "UPLOAD_IMAGE",
            "reference_index": 0,
            "invocation_no": 1,
        },
        error_code="VALIDATED_REFERENCE_UPLOAD_FAILED",
        failure_class="HTTP_ERROR",
        level="ERROR",
        stage="VIDEO_REFERENCE_UPLOAD",
        operation="UPLOAD_IMAGE",
        service="comfyui",
        provider="comfyui",
        scope={
            "book_id": "novel-1", "chapter_id": "chapter-1", "shot_id": "shot-1",
            "shot_index": 1, "clip_index": 1, "reference_index": 0,
            "task_id": task_id or f"task-{seed}", "attempt_kind": "SHOT_VIDEO",
            "attempt_id": f"attempt-{seed}", "attempt_no": 1, "retry_no": 0,
        },
        timing={"started_at": when.isoformat(), "finished_at": when.isoformat(), "elapsed_ms": 12},
        reference={"reference_index": 0, "filename": "reference.png", "bytes": 3, "sha256": digest},
        external_call={
            "endpoint": "https://comfy.invalid/upload/image?secret=discarded",
            "method": "POST", "http_status": 503,
            "exception_type": "HTTPStatusError", "exception_message": message,
            "response_body_sha256": digest, "response_body_bytes": 17,
        },
        submission={
            "queue_called": False, "submitted": False, "state": "NOT_SUBMITTED",
            "cid": None, "queue_seen": False, "remote_upload_effect": "UNKNOWN",
        },
    )
    return ExternalFailureDiagnostic.compact(detailed, evidence={
        "evidence_id": f"ev1_{digest}", "path": f"evidence-{seed}.json",
        "sha256": digest, "bytes": 128, "truncated": False, "redaction_version": 1,
    })


@pytest.mark.CANONICAL_DB
def test_observation_schema_migration_trigger_indexes_and_query_plan(db_engine, db_session):
    from migrations.add_external_failure_observations import upgrade

    upgrade(db_engine)
    upgrade(db_engine)
    schema = inspect(db_engine)
    assert "external_failure_observations" in schema.get_table_names()
    assert {"system_logs", "external_call_logs", "failure_logs"}.isdisjoint(schema.get_table_names())
    assert {column["name"] for column in schema.get_columns("external_failure_observations")} == {
        column.name for column in ExternalFailureObservation.__table__.columns
    }
    assert ("dedupe_key",) in {
        tuple(item.get("column_names") or ())
        for item in schema.get_unique_constraints("external_failure_observations")
    }
    assert {index.name for index in ExternalFailureObservation.__table__.indexes} <= {
        item["name"] for item in schema.get_indexes("external_failure_observations")
    }
    trigger = db_session.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=:name"
    ), {"name": UPDATE_TRIGGER_NAME}).scalar_one()
    assert "BEFORE UPDATE" in trigger.upper() and "RAISE(ABORT" in trigger.upper()

    row, inserted = append_external_failure_observation(db_session, diagnostic())
    assert inserted is True
    db_session.commit()
    plan = " ".join(str(item) for item in db_session.execute(text(
        "EXPLAIN QUERY PLAN SELECT id FROM external_failure_observations "
        "WHERE task_id=:task_id ORDER BY occurred_at, id"
    ), {"task_id": "task-a"}).all())
    assert "ix_external_failure_observations_task_occurred_id" in plan

    row.summary = "must not update"
    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        db_session.commit()
    db_session.rollback()
    assert db_session.get(ExternalFailureObservation, row.id).summary == "VALIDATED_REFERENCE_UPLOAD_FAILED: HTTP_ERROR"


@pytest.mark.PURE
def test_migration_creates_and_validates_a_fresh_schema_and_rejects_partial_schema():
    from migrations.add_external_failure_observations import upgrade

    engine = create_engine("sqlite:///:memory:")
    try:
        upgrade(engine)
        with engine.begin() as connection:
            upgrade(connection)
        schema = inspect(engine)
        assert schema.get_pk_constraint("external_failure_observations")["constrained_columns"] == ["id"]
        assert schema.get_foreign_keys("external_failure_observations") == []
    finally:
        engine.dispose()

    partial = create_engine("sqlite:///:memory:")
    try:
        with partial.begin() as connection:
            connection.execute(text("CREATE TABLE external_failure_observations (id TEXT PRIMARY KEY)"))
        with pytest.raises(RuntimeError, match="SCHEMA_MISMATCH"):
            upgrade(partial)
    finally:
        partial.dispose()


@pytest.mark.CANONICAL_DB
def test_observation_insert_is_idempotent_and_conflicting_evidence_is_rejected(db_session):
    original = diagnostic("dedupe", message="first failure")
    row, inserted = append_external_failure_observation(db_session, original)
    db_session.commit()
    same, inserted_again = append_external_failure_observation(db_session, original)
    assert (same.id, inserted_again) == (row.id, False)

    conflicting = diagnostic("dedupe", message="different failure evidence")
    assert conflicting["diagnostic_id"] == original["diagnostic_id"]
    with pytest.raises(ObservationConflict, match="DEDUPE_CONFLICT"):
        append_external_failure_observation(db_session, conflicting)
    assert db_session.query(ExternalFailureObservation).count() == 1


@pytest.mark.PURE
def test_stage_b_boundary_rejects_future_or_inconsistent_diagnostics():
    future = diagnostic("future")
    future["version"] = 2
    with pytest.raises(ValueError, match="INVALID_OBSERVATION_DIAGNOSTIC"):
        safe_observation_diagnostic(future)

    inconsistent = diagnostic("inconsistent")
    inconsistent["submission"]["queue_called"] = True
    with pytest.raises(ValueError, match="INVALID_NOT_SUBMITTED_FACTS"):
        safe_observation_diagnostic(inconsistent)


@pytest.mark.PURE
def test_best_effort_writer_contains_session_factory_failure():
    def unavailable():
        raise RuntimeError("observation database unavailable")

    assert record_external_failure_best_effort(
        diagnostic("factory-failure"), session_factory=unavailable,
    ) is None


@pytest.mark.CANONICAL_DB
def test_observation_insert_failure_cannot_change_business_terminal_truth(db_engine, db_session):
    task = Task(
        id="business-task", type="shot_video", status="failed", name="business truth",
        shot_id="business-shot", error_message="VALIDATED_REFERENCE_UPLOAD_FAILED",
        completed_at=datetime(2026, 9, 16, 8, 0), comfyui_prompt_id=None,
    )
    shot = Shot(
        id="business-shot", chapter_id="chapter-1", index=1,
        video_status="failed", video_task_id=task.id,
    )
    db_session.add_all([task, shot])
    db_session.commit()

    injected = []

    def fail_insert(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO EXTERNAL_FAILURE_OBSERVATIONS"):
            injected.append(True)
            raise OperationalError(statement, parameters, RuntimeError("observation insert unavailable"))

    factory = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    event.listen(db_engine, "before_cursor_execute", fail_insert)
    try:
        assert record_external_failure_best_effort(
            diagnostic("writer-failure", task_id=task.id), session_factory=factory,
        ) is None
    finally:
        event.remove(db_engine, "before_cursor_execute", fail_insert)

    db_session.expire_all()
    saved_task = db_session.get(Task, task.id)
    saved_shot = db_session.get(Shot, shot.id)
    assert injected == [True]
    assert (saved_task.status, saved_task.error_message, saved_shot.video_status) == (
        "failed", "VALIDATED_REFERENCE_UPLOAD_FAILED", "failed",
    )
    assert saved_task.comfyui_prompt_id is None
    assert "CLIP_ACK_UNKNOWN" not in saved_task.error_message
    assert db_session.query(ExternalFailureObservation).count() == 0


@pytest.mark.CANONICAL_DB
def test_observation_survives_task_deletion(db_session):
    task = Task(id="deletable-task", type="shot_video", status="failed", name="delete", error_message="FAILED")
    db_session.add(task)
    append_external_failure_observation(db_session, diagnostic("survivor", task_id=task.id))
    db_session.commit()
    observation_id = diagnostic("survivor", task_id=task.id)["diagnostic_id"]

    db_session.delete(task)
    db_session.commit()
    assert db_session.get(Task, task.id) is None
    assert db_session.get(ExternalFailureObservation, observation_id) is not None


@pytest.mark.CANONICAL_DB
def test_worker_observes_the_exact_task_it_executes(db_session, monkeypatch):
    from app.services import shot_video_execution

    first = Task(
        id="worker-first", type="shot_video", status="pending", name="first",
        created_at=datetime(2026, 9, 16, 7, 0),
    )
    second = Task(
        id="worker-second", type="shot_video", status="pending", name="second",
        created_at=datetime(2026, 9, 16, 7, 1),
    )
    db_session.add_all([first, second])
    db_session.commit()
    executed = []

    async def execute(db, task_id):
        executed.append(task_id)
        task = db.get(Task, task_id)
        value = diagnostic("worker-exact", task_id=task_id)
        task.status = "failed"
        task.error_message = "VALIDATED_REFERENCE_UPLOAD_FAILED"
        task.completed_at = datetime(2026, 9, 16, 8, 0)
        task.metadata_json = json.dumps({"video_run": {"clips": {"1": {"external_failure": value}}}})
        db.commit()

    monkeypatch.setattr(shot_video_execution, "run_video_execution", execute)
    assert asyncio.run(run_next_video_task_with_observation()) is True
    db_session.expire_all()
    assert executed == [first.id]
    assert db_session.get(Task, second.id).status == "pending"
    rows = db_session.query(ExternalFailureObservation).all()
    assert len(rows) == 1 and rows[0].task_id == first.id


def _domain_snapshot(db):
    result = {}
    for table in ("tasks", "shots", "rsa_image_attempts", "rsa_media_artifacts", "llm_logs"):
        rows = db.execute(text(f'SELECT * FROM "{table}" ORDER BY 1')).all()
        result[table] = [tuple(row) for row in rows]
    return result


@pytest.mark.CANONICAL_DB
def test_retention_deletes_only_oldest_observations_and_never_domain_rows(db_session):
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    task = Task(id="retention-task", type="shot_video", status="failed", name="retention", error_message="FAILED")
    shot = Shot(id="retention-shot", chapter_id="chapter-1", index=2, video_status="failed")
    attempt = RsaImageAttempt(
        id="retention-attempt", novel_id="novel-1", chapter_id="chapter-1", shot_id=shot.id,
        stage="KEYFRAME", frame_index=0, rsa_id="rsa-1", rsa_hash="a" * 64,
        status="FAILED", inputs={}, input_hash="b" * 64, execution={}, error="failed",
    )
    artifact = RsaMediaArtifact(
        id="retention-artifact", task_id="artifact-task", shot_id=shot.id, rsa_id="rsa-1",
        stage="KEYFRAME", frame_index=0, data={}, seal="c" * 64,
    )
    log = LLMLog(
        id="retention-llm", provider="openai", model="test", user_prompt="must remain",
        status="error", error_message="failed", created_at=now.replace(tzinfo=None),
    )
    db_session.add_all([task, shot, attempt, artifact, log])
    for seed, age in (("oldest", 130), ("old", 100), ("new", 10), ("newest", 1)):
        append_external_failure_observation(
            db_session, diagnostic(seed, when=now - timedelta(days=age), task_id=task.id),
        )
    db_session.commit()
    domain_before = _domain_snapshot(db_session)

    assert enforce_observation_retention(
        db_session, now=now, max_age_days=90, max_rows=3,
        max_logical_bytes=128 * 1024 * 1024, batch_size=1,
    ) == 1
    db_session.commit()
    remaining = db_session.query(ExternalFailureObservation).order_by(
        ExternalFailureObservation.occurred_at,
    ).all()
    assert [row.id for row in remaining] == [
        diagnostic(seed, when=now - timedelta(days=age), task_id=task.id)["diagnostic_id"]
        for seed, age in (("old", 100), ("new", 10), ("newest", 1))
    ]
    assert _domain_snapshot(db_session) == domain_before

    assert enforce_observation_retention(
        db_session, now=now, max_age_days=90, max_rows=3,
        max_logical_bytes=128 * 1024 * 1024, batch_size=1,
    ) == 1
    db_session.commit()
    assert _domain_snapshot(db_session) == domain_before
    with pytest.raises(ValueError, match="INVALID_OBSERVATION_RETENTION_LIMIT"):
        enforce_observation_retention(db_session, batch_size=501)


@pytest.mark.CANONICAL_DB
def test_retention_byte_pressure_and_default_batch_cap(db_session):
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    rows = []
    for index in range(501):
        digest = hashlib.sha256(f"retention-{index}".encode()).hexdigest()
        rows.append(ExternalFailureObservation(
            id=f"efd1_{digest}", schema_version=1, dedupe_key=digest,
            occurred_at=now - timedelta(days=200, seconds=501 - index), recorded_at=now,
            level="ERROR", service="test", provider=None, stage="TEST", operation="TEST",
            error_code="TEST_FAILURE", failure_class="UNKNOWN", summary="failure",
            diagnostic_json=json.dumps({"index": index}), evidence_bytes=100,
        ))
    db_session.add_all(rows)
    db_session.commit()
    assert enforce_observation_retention(db_session, now=now) == 500
    db_session.commit()
    assert db_session.query(ExternalFailureObservation).count() == 1

    remaining = db_session.query(ExternalFailureObservation).one()
    remaining_id = remaining.id
    assert enforce_observation_retention(
        db_session, now=now, max_age_days=1000, max_rows=10,
        max_logical_bytes=1, batch_size=1,
    ) == 1
    db_session.commit()
    assert db_session.get(ExternalFailureObservation, remaining_id) is None


@pytest.mark.PURE
def test_observation_model_imports_are_confined_to_stage_b_boundaries():
    backend = Path(__file__).resolve().parents[1]
    allowed = {
        Path("app/models/__init__.py"),
        Path("app/services/external_failure_observation_service.py"),
        Path("app/services/system_log_service.py"),
        Path("app/services/sqlite_schema_upgrade.py"),
        Path("migrations/add_external_failure_observations.py"),
    }
    offenders = []
    for path in (backend / "app").rglob("*.py"):
        relative = path.relative_to(backend)
        if relative == Path("app/models/external_failure_observation.py"):
            continue
        if "app.models.external_failure_observation" in path.read_text(encoding="utf-8") and relative not in allowed:
            offenders.append(str(relative))
    assert offenders == []
