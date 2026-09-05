from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.database import Base


def _is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


def _table_exists(conn, table_name: str) -> bool:
    return bool(inspect(conn).has_table(table_name))


def _columns(conn, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    result = conn.execute(text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result.fetchall()}


def _add_column_if_missing(conn, table_name: str, column_name: str, ddl: str) -> None:
    if column_name not in _columns(conn, table_name):
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def _create_index(conn, ddl: str) -> None:
    conn.execute(text(ddl))


def upgrade_sqlite_schema(engine: Engine) -> None:
    """Idempotent SQLite upgrade path for existing local databases."""
    if not _is_sqlite(engine):
        return

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        if _table_exists(conn, "shots"):
            _add_column_if_missing(conn, "shots", "merged_prop_image", "merged_prop_image VARCHAR")
            _add_column_if_missing(conn, "shots", "continuity_mode", "continuity_mode VARCHAR DEFAULT 'NORMAL'")
            _add_column_if_missing(conn, "shots", "video_director_plan", "video_director_plan TEXT DEFAULT '{}'")
            _add_column_if_missing(conn, "shots", "video_director_plan_revision", "video_director_plan_revision INTEGER DEFAULT 0")
            _add_column_if_missing(conn, "shots", "shot_image_prompt", "shot_image_prompt TEXT DEFAULT ''")
            _add_column_if_missing(conn, "shots", "estimated_duration", "estimated_duration INTEGER")
            _add_column_if_missing(conn, "shots", "audio_status", "audio_status VARCHAR DEFAULT 'NOT_READY'")

        if _table_exists(conn, "shot_audio_timelines"):
            _add_column_if_missing(conn, "shot_audio_timelines", "audio_required_duration", "audio_required_duration FLOAT")

        if _table_exists(conn, "novels"):
            for column in [
                "keyframe_description_prompt_template_id",
                "shot_image_prompt_template_id",
                "video_mode_recommender_prompt_template_id",
                "keyframe_planner_prompt_template_id",
                "keyframe_image_prompt_template_id",
                "keyframe_transition_prompt_template_id",
                "h3_single_frame_prompt_template_id",
                "h3_first_last_frame_prompt_template_id",
                "h3_multi_keyframe_prompt_template_id",
            ]:
                _add_column_if_missing(conn, "novels", column, f"{column} VARCHAR")

        if _table_exists(conn, "tasks"):
            _add_column_if_missing(conn, "tasks", "reference_images", "reference_images TEXT")
            _add_column_if_missing(conn, "tasks", "video_director_clips", "video_director_clips TEXT")
            _add_column_if_missing(conn, "tasks", "parent_task_id", "parent_task_id VARCHAR")
            _add_column_if_missing(conn, "tasks", "batch_order", "batch_order INTEGER")
            _add_column_if_missing(conn, "tasks", "metadata_json", "metadata_json TEXT")
            _add_column_if_missing(conn, "tasks", "worker_id", "worker_id VARCHAR")
            _add_column_if_missing(conn, "tasks", "claim_token", "claim_token VARCHAR")
            _add_column_if_missing(conn, "tasks", "claimed_at", "claimed_at DATETIME")
            _add_column_if_missing(conn, "tasks", "heartbeat_at", "heartbeat_at DATETIME")
            _add_column_if_missing(conn, "tasks", "attempt", "attempt INTEGER DEFAULT 0")

        if _table_exists(conn, "llm_logs"):
            _add_column_if_missing(conn, "llm_logs", "request_info", "request_info TEXT")
            _add_column_if_missing(conn, "llm_logs", "prompt_template_name", "prompt_template_name VARCHAR")

        _create_index(conn, "CREATE INDEX IF NOT EXISTS ix_shots_audio_status ON shots (audio_status)")
        _create_index(conn, "CREATE INDEX IF NOT EXISTS ix_shots_chapter_index ON shots (chapter_id, \"index\")")
        _create_index(conn, "CREATE INDEX IF NOT EXISTS ix_tasks_parent_task_id ON tasks (parent_task_id)")
        _create_index(conn, "CREATE INDEX IF NOT EXISTS ix_audio_event_tts_current ON audio_event_tts_assets (audio_event_id, is_current)")
        _create_index(conn, "CREATE INDEX IF NOT EXISTS ix_shot_audio_events_shot_order ON shot_audio_events (shot_id, event_order)")
        _create_index(conn, "CREATE INDEX IF NOT EXISTS ix_shot_audio_timelines_shot_revision ON shot_audio_timelines (shot_id, revision)")
        _create_index(conn, "CREATE INDEX IF NOT EXISTS ix_shot_audio_timeline_events_timeline_order ON shot_audio_timeline_events (timeline_id, event_order)")
        cleanup_audiodrive_orphans(conn)


def audiodrive_orphan_counts(conn) -> dict[str, int]:
    tables = inspect(conn).get_table_names()
    required = {"shots", "shot_audio_events", "audio_event_tts_assets", "shot_audio_timelines", "shot_audio_timeline_events"}
    if not required.issubset(set(tables)):
        return {}
    checks = {
        "shot_audio_events_orphan": """
            SELECT COUNT(*) FROM shot_audio_events e
            LEFT JOIN shots s ON s.id = e.shot_id
            WHERE s.id IS NULL
        """,
        "tts_assets_orphan": """
            SELECT COUNT(*) FROM audio_event_tts_assets a
            LEFT JOIN shot_audio_events e ON e.id = a.audio_event_id
            WHERE e.id IS NULL
        """,
        "timelines_orphan": """
            SELECT COUNT(*) FROM shot_audio_timelines t
            LEFT JOIN shots s ON s.id = t.shot_id
            WHERE s.id IS NULL
        """,
        "timeline_events_timeline_orphan": """
            SELECT COUNT(*) FROM shot_audio_timeline_events te
            LEFT JOIN shot_audio_timelines t ON t.id = te.timeline_id
            WHERE t.id IS NULL
        """,
        "timeline_events_event_orphan": """
            SELECT COUNT(*) FROM shot_audio_timeline_events te
            LEFT JOIN shot_audio_events e ON e.id = te.audio_event_id
            WHERE e.id IS NULL
        """,
        "timeline_events_tts_orphan": """
            SELECT COUNT(*) FROM shot_audio_timeline_events te
            LEFT JOIN audio_event_tts_assets a ON a.id = te.tts_asset_id
            WHERE te.tts_asset_id IS NOT NULL AND a.id IS NULL
        """,
    }
    return {name: int(conn.execute(text(sql)).scalar() or 0) for name, sql in checks.items()}


def cleanup_audiodrive_orphans(conn) -> None:
    tables = inspect(conn).get_table_names()
    required = {"shots", "shot_audio_events", "audio_event_tts_assets", "shot_audio_timelines", "shot_audio_timeline_events"}
    if not required.issubset(set(tables)):
        return
    _cleanup_audiodrive_leaf_orphans(conn)
    conn.execute(text("""
        DELETE FROM shot_audio_timelines
        WHERE NOT EXISTS (SELECT 1 FROM shots WHERE shots.id = shot_audio_timelines.shot_id)
    """))
    conn.execute(text("""
        DELETE FROM shot_audio_events
        WHERE NOT EXISTS (SELECT 1 FROM shots WHERE shots.id = shot_audio_events.shot_id)
    """))
    _cleanup_audiodrive_leaf_orphans(conn)


def _cleanup_audiodrive_leaf_orphans(conn) -> None:
    conn.execute(text("""
        DELETE FROM audio_event_tts_assets
        WHERE NOT EXISTS (SELECT 1 FROM shot_audio_events WHERE shot_audio_events.id = audio_event_tts_assets.audio_event_id)
    """))
    conn.execute(text("""
        DELETE FROM shot_audio_timeline_events
        WHERE NOT EXISTS (SELECT 1 FROM shot_audio_timelines WHERE shot_audio_timelines.id = shot_audio_timeline_events.timeline_id)
    """))
    conn.execute(text("""
        DELETE FROM shot_audio_timeline_events
        WHERE NOT EXISTS (SELECT 1 FROM shot_audio_events WHERE shot_audio_events.id = shot_audio_timeline_events.audio_event_id)
    """))
    conn.execute(text("""
        DELETE FROM shot_audio_timeline_events
        WHERE tts_asset_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM audio_event_tts_assets WHERE audio_event_tts_assets.id = shot_audio_timeline_events.tts_asset_id)
    """))


def assert_audiodrive_integrity(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        counts = audiodrive_orphan_counts(conn)
    bad = {name: count for name, count in counts.items() if count}
    if bad:
        raise RuntimeError(f"AudioDrive integrity check failed: {bad}")
    return counts
