"""Additive Phase3 schema upgrade; no event positioning/backfill during migration."""
from sqlalchemy import inspect, text
from app.models.appearance_timeline import CharacterAppearance, AppearanceEventReview, AppearanceTimelineRun


def upgrade(bind):
    with bind.begin() as connection:
        for model in (CharacterAppearance, AppearanceEventReview, AppearanceTimelineRun):
            model.__table__.create(connection, checkfirst=True)
        table = "chapter_character_appearance_events"
        if not inspect(connection).has_table(table):
            return
        columns = {column["name"] for column in inspect(connection).get_columns(table)}
        for name, datatype in (("resolved_appearance_id", "VARCHAR"), ("location_proof", "JSON"), ("located_source_hash", "VARCHAR")):
            if name not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {datatype}"))
