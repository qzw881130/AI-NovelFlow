#!/usr/bin/env python3
"""
迁移脚本：为 prompt_templates 表添加 type 字段
"""
import sqlite3
import os

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), "novelflow.db")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 检查是否存在 type 字段
    cursor.execute("PRAGMA table_info(prompt_templates)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'type' not in columns:
        print("添加 type 字段到 prompt_templates 表...")
        cursor.execute("ALTER TABLE prompt_templates ADD COLUMN type VARCHAR(50) DEFAULT 'character'")
        conn.commit()
        print("✅ type 字段添加成功")
    else:
        print("type 字段已存在，跳过迁移")
    
    # 显示当前数据
    cursor.execute("SELECT id, name, type FROM prompt_templates LIMIT 5")
    rows = cursor.fetchall()
    print("\n当前提示词模板数据:")
    for row in rows:
        print(f"  - {row[1]} ({row[2]})")
    
    conn.close()
    print("\n✅ 迁移完成")

if __name__ == "__main__":
    migrate()
