#!/usr/bin/env python3
"""
数据库迁移脚本：为 shots 表添加合并道具图字段
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text

from app.core.database import engine


def upgrade():
    """添加 merged_prop_image 字段"""
    print("正在添加合并道具图字段...")

    with engine.connect() as conn:
        try:
            result = conn.execute(text("PRAGMA table_info(shots)"))
            shot_columns = [row[1] for row in result.fetchall()]

            if 'merged_prop_image' not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN merged_prop_image VARCHAR"))
                print("已添加 merged_prop_image 字段到 shots 表")

            conn.commit()
            print("合并道具图字段添加成功！")
        except Exception as e:
            print(f"添加字段时出错: {e}")
            conn.rollback()


if __name__ == "__main__":
    upgrade()
