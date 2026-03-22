#!/usr/bin/env python3
"""
数据库迁移脚本：添加关键帧、参考音频和旁白支持字段
- characters表添加 is_narrator 字段
- shots表添加 keyframes 和 reference_audio_url 字段
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.core.database import engine
from sqlalchemy import text

def upgrade():
    """添加关键帧和旁白相关字段"""

    print("正在添加关键帧和旁白支持字段...")

    with engine.connect() as conn:
        try:
            # ===== characters 表 =====
            result = conn.execute(text("PRAGMA table_info(characters)"))
            char_columns = [row[1] for row in result.fetchall()]

            # 添加旁白标识字段
            if 'is_narrator' not in char_columns:
                conn.execute(text("ALTER TABLE characters ADD COLUMN is_narrator BOOLEAN DEFAULT 0"))
                print("已添加 is_narrator 字段到 characters 表")

            # ===== shots 表 =====
            result = conn.execute(text("PRAGMA table_info(shots)"))
            shot_columns = [row[1] for row in result.fetchall()]

            # 添加关键帧字段
            if 'keyframes' not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN keyframes TEXT DEFAULT '[]'"))
                print("已添加 keyframes 字段到 shots 表")

            # 添加参考音频URL字段
            if 'reference_audio_url' not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN reference_audio_url VARCHAR"))
                print("已添加 reference_audio_url 字段到 shots 表")

            conn.commit()
            print("关键帧和旁白支持字段添加成功！")

        except Exception as e:
            print(f"添加字段时出错: {e}")
            conn.rollback()

def downgrade():
    """回滚字段更改（谨慎使用）"""
    print("警告：此操作将删除新增的字段，可能导致数据丢失！")
    response = input("确认要回滚吗？(y/N): ")
    if response.lower() != 'y':
        print("操作已取消")
        return

    with engine.connect() as conn:
        try:
            print("注意：SQLite不支持直接删除列，请手动处理或重建表")
            print("请考虑以下方案：")
            print("1. 备份数据后重建相关表")
            print("2. 或者保留现有字段（推荐）")
            print("字段删除操作已跳过")
            conn.commit()
        except Exception as e:
            print(f"检查字段时出错: {e}")
            conn.rollback()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "downgrade":
        downgrade()
    else:
        upgrade()