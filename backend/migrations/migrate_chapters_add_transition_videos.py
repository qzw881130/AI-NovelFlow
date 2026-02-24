#!/usr/bin/env python3
"""
迁移脚本：为 chapters 表添加 transition_videos 字段
"""
import sqlite3
import os

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), "novelflow.db")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 检查是否存在 transition_videos 字段
    cursor.execute("PRAGMA table_info(chapters)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'transition_videos' not in columns:
        print("添加 transition_videos 字段到 chapters 表...")
        cursor.execute("ALTER TABLE chapters ADD COLUMN transition_videos TEXT")
        conn.commit()
        print("✅ transition_videos 字段添加成功")
    else:
        print("transition_videos 字段已存在，跳过迁移")
    
    # 检查是否还有其他可能缺少的列（比如 updated_at 默认值等）
    
    conn.close()
    print("\n✅ 迁移完成")

if __name__ == "__main__":
    migrate()
