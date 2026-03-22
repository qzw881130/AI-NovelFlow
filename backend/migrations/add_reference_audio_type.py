"""
数据库迁移：添加 reference_audio_type 字段到 shots 表

运行方式：python migrations/add_reference_audio_type.py
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine


def migrate():
    """添加 reference_audio_type 字段"""
    with engine.connect() as conn:
        # 检查字段是否已存在
        result = conn.execute(text("PRAGMA table_info(shots)"))
        columns = [row[1] for row in result.fetchall()]

        if "reference_audio_type" not in columns:
            print("Adding reference_audio_type column to shots table...")
            conn.execute(text(
                "ALTER TABLE shots ADD COLUMN reference_audio_type VARCHAR DEFAULT 'none'"
            ))
            conn.commit()
            print("Migration completed successfully!")
        else:
            print("Column reference_audio_type already exists, skipping migration.")


if __name__ == "__main__":
    migrate()