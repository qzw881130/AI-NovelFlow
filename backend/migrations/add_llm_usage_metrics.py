"""Add provider-reported token usage metrics to LLM logs."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text


def migrate():
    engine = create_engine("sqlite:///./novelflow.db")
    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(llm_logs)")).fetchall()]
        if "usage_metrics" not in columns:
            conn.execute(text("ALTER TABLE llm_logs ADD COLUMN usage_metrics JSON"))
            conn.commit()
            print("Added usage_metrics column to llm_logs")
        else:
            print("usage_metrics column already exists")


if __name__ == "__main__":
    migrate()
