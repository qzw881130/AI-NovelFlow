"""Add the isolated grid-mode storage columns without reclassifying old data."""

from sqlalchemy import text

from app.core.database import engine


GRID_NOVEL_TEMPLATE_COLUMNS = (
    "grid_shot_plan_prompt_template_id",
    "grid_image_prompt_template_id",
    "grid_clip_plan_prompt_template_id",
    "grid_h3_phase_b_prompt_template_id",
)


def upgrade_connection(conn) -> None:
    novel_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(novels)"))}
    if "video_mode" not in novel_columns:
        conn.execute(text("ALTER TABLE novels ADD COLUMN video_mode VARCHAR NOT NULL DEFAULT 'single'"))
    # Covers a pre-existing nullable experimental column as well.
    conn.execute(text("UPDATE novels SET video_mode='single' WHERE video_mode IS NULL OR video_mode=''"))
    for column in GRID_NOVEL_TEMPLATE_COLUMNS:
        if column not in novel_columns:
            conn.execute(text(f"ALTER TABLE novels ADD COLUMN {column} VARCHAR"))

    shot_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(shots)"))}
    if "grid_data" not in shot_columns:
        conn.execute(text("ALTER TABLE shots ADD COLUMN grid_data TEXT"))


def run_migration() -> None:
    with engine.begin() as conn:
        upgrade_connection(conn)


if __name__ == "__main__":
    run_migration()
