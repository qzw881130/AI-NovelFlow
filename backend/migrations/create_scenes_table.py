#!/usr/bin/env python3
"""
数据库迁移脚本：创建或更新scenes表，并为tasks表添加scene_id字段
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.core.database import engine
from sqlalchemy import text


def upgrade():
    """创建或更新scenes表，并为tasks表添加scene_id字段"""
    
    # 首先为tasks表添加scene_id字段
    print("正在检查tasks表...")
    with engine.connect() as conn:
        try:
            result = conn.execute(text("PRAGMA table_info(tasks)"))
            columns = [row[1] for row in result.fetchall()]
            
            if 'scene_id' not in columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN scene_id VARCHAR"))
                conn.commit()
                print("已为tasks表添加 scene_id 字段")
            else:
                print("tasks.scene_id 字段已存在，跳过")
        except Exception as e:
            print(f"添加tasks.scene_id字段时出错: {e}")
            conn.rollback()
    
    # 创建或更新scenes表
    print("\n正在检查scenes表...")
    
    with engine.connect() as conn:
        try:
            # 检查表是否存在
            result = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='scenes'"
            ))
            table_exists = result.fetchone() is not None
            
            if not table_exists:
                print("scenes表不存在，正在创建...")
                conn.execute(text("""
                    CREATE TABLE scenes (
                        id VARCHAR PRIMARY KEY,
                        novel_id VARCHAR NOT NULL,
                        name VARCHAR NOT NULL,
                        description TEXT DEFAULT '',
                        setting TEXT DEFAULT '',
                        image_url VARCHAR,
                        start_chapter INTEGER,
                        end_chapter INTEGER,
                        generating_status VARCHAR,
                        scene_task_id VARCHAR,
                        is_incremental BOOLEAN DEFAULT 0,
                        source_range VARCHAR,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP,
                        last_parsed_at TIMESTAMP,
                        FOREIGN KEY (novel_id) REFERENCES novels(id)
                    )
                """))
                conn.commit()
                print("scenes表创建成功！")
            else:
                print("scenes表已存在，检查并添加缺失字段...")
                
                # 获取现有字段
                result = conn.execute(text("PRAGMA table_info(scenes)"))
                columns = [row[1] for row in result.fetchall()]
                
                # 定义需要检查的字段
                fields_to_add = [
                    ("description", "TEXT DEFAULT ''"),
                    ("setting", "TEXT DEFAULT ''"),
                    ("image_url", "VARCHAR"),
                    ("start_chapter", "INTEGER"),
                    ("end_chapter", "INTEGER"),
                    ("generating_status", "VARCHAR"),
                    ("scene_task_id", "VARCHAR"),
                    ("is_incremental", "BOOLEAN DEFAULT 0"),
                    ("source_range", "VARCHAR"),
                    ("last_parsed_at", "TIMESTAMP"),
                ]
                
                # 添加缺失的字段
                added_count = 0
                for field_name, field_type in fields_to_add:
                    if field_name not in columns:
                        conn.execute(text(f"ALTER TABLE scenes ADD COLUMN {field_name} {field_type}"))
                        print(f"已添加 {field_name} 字段")
                        added_count += 1
                
                if added_count == 0:
                    print("所有字段已存在，无需更新")
                
                conn.commit()
                print("迁移完成！")
                
        except Exception as e:
            print(f"迁移时出错: {e}")
            conn.rollback()
            raise


def check_table_structure():
    """检查并打印scenes表结构"""
    with engine.connect() as conn:
        try:
            result = conn.execute(text("PRAGMA table_info(scenes)"))
            columns = result.fetchall()
            
            print("\nscenes表当前结构:")
            print("-" * 60)
            print(f"{'序号':<6} {'字段名':<20} {'类型':<15} {'非空':<6} {'默认值'}")
            print("-" * 60)
            for col in columns:
                print(f"{col[0]:<6} {col[1]:<20} {col[2]:<15} {col[3]:<6} {col[4]}")
            print("-" * 60)
            
        except Exception as e:
            print(f"检查表结构时出错: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        check_table_structure()
    else:
        upgrade()
        check_table_structure()
