from sqlalchemy import inspect, text
from app.models.appearance_generation import AppearanceGeneration, AppearanceImageRevision, AppearanceShotUsage


def upgrade(bind):
    with bind.begin() as connection:
        for model in (AppearanceGeneration, AppearanceImageRevision, AppearanceShotUsage):
            model.__table__.create(connection, checkfirst=True)
        if inspect(connection).has_table("character_appearances"):
            columns = {c["name"] for c in inspect(connection).get_columns("character_appearances")}
            for name, definition in (("reference_image_revision_id", "VARCHAR"), ("generation_revision", "INTEGER NOT NULL DEFAULT 0"), ("last_error", "TEXT")):
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE character_appearances ADD COLUMN {name} {definition}"))
