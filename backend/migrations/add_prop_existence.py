"""Add semantic existence classification to props."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text


def migrate():
    engine = create_engine("sqlite:///./novelflow.db")
    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(props)")).fetchall()]
        if "existence" not in columns:
            conn.execute(text("ALTER TABLE props ADD COLUMN existence VARCHAR NOT NULL DEFAULT 'REAL'"))
            print("Added existence column to props")
        else:
            print("existence column already exists")
        conn.execute(text("""
            UPDATE props SET existence = 'FICTIONAL_OR_NONEXISTENT'
            WHERE existence = 'REAL'
              AND (description LIKE '%不存在%' OR description LIKE '%并不真实%' OR description LIKE '%仅为谎言%')
        """))
        conn.execute(text("""
            UPDATE shots SET merged_prop_image = NULL
            WHERE chapter_id IN (
                SELECT id FROM chapters WHERE novel_id IN (
                    SELECT DISTINCT novel_id FROM props WHERE existence = 'FICTIONAL_OR_NONEXISTENT'
                )
            )
        """))
        conn.commit()


if __name__ == "__main__":
    migrate()
