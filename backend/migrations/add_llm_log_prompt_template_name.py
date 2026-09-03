"""
迁移脚本：为 llm_logs 表添加 prompt_template_name 字段
运行: cd backend && python migrations/add_llm_log_prompt_template_name.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

DATABASE_URL = "sqlite:///./novelflow.db"


def migrate():
    """添加 prompt_template_name 列到 llm_logs 表"""
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        try:
            result = conn.execute(text("PRAGMA table_info(llm_logs)"))
            columns = [row[1] for row in result.fetchall()]

            if "prompt_template_name" not in columns:
                conn.execute(text("ALTER TABLE llm_logs ADD COLUMN prompt_template_name VARCHAR"))
                print("✓ Added prompt_template_name column to llm_logs table")
            else:
                print("✓ prompt_template_name column already exists")

            conn.commit()
        except Exception as e:
            print(f"✗ Error: {e}")
            conn.rollback()

    print("\n✅ Migration completed!")


if __name__ == "__main__":
    migrate()
