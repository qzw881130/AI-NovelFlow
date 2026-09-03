"""Add V2 prompt template selection columns to novels table."""

from sqlalchemy import create_engine, text

from app.core.config import get_settings


NOVEL_PROMPT_COLUMNS = [
    "keyframe_description_prompt_template_id",
    "shot_image_prompt_template_id",
    "video_mode_recommender_prompt_template_id",
    "keyframe_planner_prompt_template_id",
    "keyframe_image_prompt_template_id",
    "keyframe_transition_prompt_template_id",
    "h3_single_frame_prompt_template_id",
    "h3_first_last_frame_prompt_template_id",
    "h3_multi_keyframe_prompt_template_id",
]


def main():
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(novels)")).fetchall()]
        added = []
        for column in NOVEL_PROMPT_COLUMNS:
            if column not in columns:
                conn.execute(text(f"ALTER TABLE novels ADD COLUMN {column} VARCHAR"))
                added.append(column)
        conn.commit()
        if added:
            print("Added columns: " + ", ".join(added))
        else:
            print("All V2 novel prompt template columns already exist")


if __name__ == "__main__":
    main()
