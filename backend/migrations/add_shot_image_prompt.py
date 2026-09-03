"""Add shot_image_prompt column to shots table."""

from sqlalchemy import text

from app.core.database import engine


def run_migration():
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(shots)"))
        columns = [row[1] for row in result.fetchall()]
        if "shot_image_prompt" not in columns:
            conn.execute(text("ALTER TABLE shots ADD COLUMN shot_image_prompt TEXT DEFAULT ''"))
            conn.commit()
            print("Added shots.shot_image_prompt")
        else:
            print("shots.shot_image_prompt already exists")


if __name__ == "__main__":
    run_migration()
