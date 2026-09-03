"""Add video_director_plan to shots table."""

from sqlalchemy import text

from app.core.database import engine


def column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(text(f"PRAGMA table_info({table_name})"))
    return column_name in [row[1] for row in result.fetchall()]


def run_migration():
    with engine.connect() as conn:
        if not column_exists(conn, "shots", "video_director_plan"):
            conn.execute(text("ALTER TABLE shots ADD COLUMN video_director_plan TEXT DEFAULT '{}'"))
            conn.commit()
            print("Added shots.video_director_plan")
        else:
            print("shots.video_director_plan already exists")


if __name__ == "__main__":
    run_migration()
