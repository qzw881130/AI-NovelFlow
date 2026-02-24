#!/usr/bin/env python3
"""
迁移脚本：为 novels 表添加 chapter_split_prompt_template_id 字段
"""
import sqlite3
import os

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), "novelflow.db")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 检查是否存在 chapter_split_prompt_template_id 字段
    cursor.execute("PRAGMA table_info(novels)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'chapter_split_prompt_template_id' not in columns:
        print("添加 chapter_split_prompt_template_id 字段到 novels 表...")
        cursor.execute("ALTER TABLE novels ADD COLUMN chapter_split_prompt_template_id VARCHAR(50)")
        conn.commit()
        print("✅ 字段添加成功")
    else:
        print("chapter_split_prompt_template_id 字段已存在，跳过迁移")
    
    conn.close()
    print("\n✅ 迁移完成")

if __name__ == "__main__":
    migrate()
