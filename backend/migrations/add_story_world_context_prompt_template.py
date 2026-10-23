"""Add the per-novel story world context prompt template selection."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text


def migrate():
    engine = create_engine("sqlite:///./novelflow.db")
    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(novels)")).fetchall()]
        definitions = {
            "story_world_context_prompt_template_id": "VARCHAR",
            "story_world_context": "TEXT",
            "story_world_context_locked": "BOOLEAN DEFAULT 0",
            "story_world_context_updated_at": "DATETIME",
        }
        for column, definition in definitions.items():
            if column not in columns:
                conn.execute(text(f"ALTER TABLE novels ADD COLUMN {column} {definition}"))
                print(f"Added {column} column to novels")
            else:
                print(f"{column} column already exists")
        conn.commit()


if __name__ == "__main__":
    migrate()
