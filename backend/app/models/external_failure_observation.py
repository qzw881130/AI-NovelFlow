"""Append-only, non-authoritative observations of external failures."""

from sqlalchemy import Column, DateTime, DDL, Index, Integer, String, Text, UniqueConstraint, event, inspect

from app.core.database import Base


UPDATE_TRIGGER_NAME = "trg_external_failure_observations_no_update"
UPDATE_TRIGGER_DDL = f"""
CREATE TRIGGER IF NOT EXISTS {UPDATE_TRIGGER_NAME}
BEFORE UPDATE ON external_failure_observations
BEGIN
    SELECT RAISE(ABORT, 'external_failure_observations are append-only');
END
"""


class ExternalFailureObservation(Base):
    __tablename__ = "external_failure_observations"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_external_failure_observations_dedupe_key"),
        Index("ix_external_failure_observations_occurred_id", "occurred_at", "id"),
        Index("ix_external_failure_observations_task_occurred_id", "task_id", "occurred_at", "id"),
        Index(
            "ix_external_failure_observations_scope_occurred_id",
            "novel_id", "chapter_id", "shot_id", "occurred_at", "id",
        ),
        Index(
            "ix_external_failure_observations_service_failure_occurred_id",
            "service", "failure_class", "occurred_at", "id",
        ),
        Index("ix_external_failure_observations_level_occurred_id", "level", "occurred_at", "id"),
        Index(
            "ix_external_failure_observations_error_code_occurred_id",
            "error_code", "occurred_at", "id",
        ),
    )

    id = Column(String(69), primary_key=True)
    schema_version = Column(Integer, nullable=False)
    dedupe_key = Column(String(64), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False)

    level = Column(String(32), nullable=False)
    service = Column(String(128), nullable=False)
    provider = Column(String(128), nullable=True)
    stage = Column(String(128), nullable=False)
    operation = Column(String(128), nullable=False)
    error_code = Column(String(128), nullable=False)
    failure_class = Column(String(64), nullable=False)

    novel_id = Column(String(256), nullable=True)
    chapter_id = Column(String(256), nullable=True)
    shot_id = Column(String(256), nullable=True)
    shot_index = Column(Integer, nullable=True)
    clip_index = Column(Integer, nullable=True)
    frame_index = Column(Integer, nullable=True)
    reference_index = Column(Integer, nullable=True)
    task_id = Column(String(256), nullable=True)
    attempt_kind = Column(String(128), nullable=True)
    attempt_id = Column(String(256), nullable=True)
    attempt_no = Column(Integer, nullable=True)
    retry_no = Column(Integer, nullable=True)

    http_status = Column(Integer, nullable=True)
    submission_state = Column(String(64), nullable=True)
    cid = Column(String(256), nullable=True)
    summary = Column(Text, nullable=False)
    diagnostic_json = Column(Text, nullable=False)

    evidence_id = Column(String(68), nullable=True)
    evidence_path = Column(String(512), nullable=True)
    evidence_sha256 = Column(String(64), nullable=True)
    evidence_bytes = Column(Integer, nullable=True)


event.listen(
    ExternalFailureObservation.__table__,
    "after_create",
    DDL(UPDATE_TRIGGER_DDL).execute_if(dialect="sqlite"),
)


def ensure_sqlite_update_trigger(connection) -> None:
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {UPDATE_TRIGGER_NAME}")
        connection.exec_driver_sql(UPDATE_TRIGGER_DDL)


def ensure_external_failure_observation_schema(connection) -> None:
    """Create or verify the sole Stage B table without accepting a partial draft."""
    table = ExternalFailureObservation.__table__
    table.create(connection, checkfirst=True)
    inspector = inspect(connection)
    model_columns = {column.name: column for column in table.columns}
    actual_column_list = inspector.get_columns(table.name)
    actual_columns = {column["name"]: column for column in actual_column_list}
    if set(actual_columns) != set(model_columns):
        raise RuntimeError("EXTERNAL_FAILURE_OBSERVATION_SCHEMA_MISMATCH")
    for name, model_column in model_columns.items():
        actual = actual_columns[name]
        if (actual["type"]._type_affinity is not model_column.type._type_affinity
                or bool(actual["nullable"]) != bool(model_column.nullable)):
            raise RuntimeError("EXTERNAL_FAILURE_OBSERVATION_SCHEMA_MISMATCH")
    primary_key = tuple(inspector.get_pk_constraint(table.name).get("constrained_columns") or ())
    if primary_key != ("id",):
        raise RuntimeError("EXTERNAL_FAILURE_OBSERVATION_PRIMARY_KEY_MISMATCH")
    if inspector.get_foreign_keys(table.name):
        raise RuntimeError("EXTERNAL_FAILURE_OBSERVATION_FOREIGN_KEY_FORBIDDEN")
    unique_sets = {
        tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints(table.name)
    }
    if ("dedupe_key",) not in unique_sets:
        raise RuntimeError("EXTERNAL_FAILURE_OBSERVATION_DEDUPE_CONSTRAINT_MISSING")
    for index in table.indexes:
        index.create(connection, checkfirst=True)
    ensure_sqlite_update_trigger(connection)
    inspector = inspect(connection)
    expected_indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in table.indexes
    }
    actual_indexes = {
        index["name"]: tuple(index.get("column_names") or ())
        for index in inspector.get_indexes(table.name)
    }
    if any(actual_indexes.get(name) != columns for name, columns in expected_indexes.items()):
        raise RuntimeError("EXTERNAL_FAILURE_OBSERVATION_INDEX_MISSING")


__all__ = [
    "ExternalFailureObservation", "UPDATE_TRIGGER_DDL", "UPDATE_TRIGGER_NAME",
    "ensure_external_failure_observation_schema", "ensure_sqlite_update_trigger",
]
