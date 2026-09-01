"""Add continuity_mode column to shots table."""

from sqlalchemy import create_engine, text

from app.core.config import get_settings


def main():
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(shots)")).fetchall()]
        if "continuity_mode" not in columns:
            conn.execute(text("ALTER TABLE shots ADD COLUMN continuity_mode VARCHAR DEFAULT 'NORMAL'"))
            conn.commit()
            print("Added shots.continuity_mode")
        else:
            print("shots.continuity_mode already exists")


if __name__ == "__main__":
    main()
