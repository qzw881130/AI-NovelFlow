"""
迁移脚本：为 tasks 表添加 shot_id 字段
运行: cd backend && python migrations/add_task_shot_id.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

DATABASE_URL = "sqlite:///./novelflow.db"

def migrate():
    """添加 shot_id 列到 tasks 表"""
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        try:
            # 检查字段是否已存在
            result = conn.execute(text("PRAGMA table_info(tasks)"))
            columns = [row[1] for row in result.fetchall()]

            if 'shot_id' not in columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN shot_id VARCHAR"))
                # 创建索引
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_shot_id ON tasks (shot_id)"))
                print("[OK] Added shot_id column to tasks table")
            else:
                print("[OK] shot_id column already exists")

            conn.commit()
        except Exception as e:
            print(f"[ERROR] {e}")
            conn.rollback()

    print("\n[DONE] Migration completed!")

if __name__ == "__main__":
    migrate()