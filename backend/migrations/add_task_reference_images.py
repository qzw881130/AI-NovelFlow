#!/usr/bin/env python3
"""
数据库迁移脚本：为 tasks 表添加参考图记录字段
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text

from app.core.database import engine


def upgrade():
    """添加 reference_images 字段"""
    print("正在添加任务参考图字段...")

    with engine.connect() as conn:
        try:
            result = conn.execute(text("PRAGMA table_info(tasks)"))
            task_columns = [row[1] for row in result.fetchall()]

            if 'reference_images' not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN reference_images TEXT"))
                print("已添加 reference_images 字段到 tasks 表")

            conn.commit()
            print("任务参考图字段添加成功！")
        except Exception as e:
            print(f"添加字段时出错: {e}")
            conn.rollback()


if __name__ == "__main__":
    upgrade()
