#!/usr/bin/env python3
"""
数据库迁移脚本：为Character表添加章节范围和增量更新字段
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.core.database import engine
from app.models.novel import Character
from sqlalchemy import Column, Integer, Boolean, String, DateTime, text

def upgrade():
    """添加新的字段到characters表"""
    # 注意：在生产环境中应该使用Alembic进行正式的数据库迁移
    # 这里提供手动SQL语句作为参考
    
    print("正在为characters表添加章节范围字段...")
    
    # 添加章节范围字段
    with engine.connect() as conn:
        try:
            # 检查字段是否已存在
            result = conn.execute(text("PRAGMA table_info(characters)"))
            columns = [row[1] for row in result.fetchall()]
            
            # 添加起始章节字段
            if 'start_chapter' not in columns:
                conn.execute(text("ALTER TABLE characters ADD COLUMN start_chapter INTEGER"))
                print("已添加 start_chapter 字段")
            
            # 添加结束章节字段
            if 'end_chapter' not in columns:
                conn.execute(text("ALTER TABLE characters ADD COLUMN end_chapter INTEGER"))
                print("已添加 end_chapter 字段")
            
            # 添加增量更新标记字段
            if 'is_incremental' not in columns:
                conn.execute(text("ALTER TABLE characters ADD COLUMN is_incremental BOOLEAN DEFAULT FALSE"))
                print("已添加 is_incremental 字段")
            
            # 添加数据来源范围描述字段
            if 'source_range' not in columns:
                conn.execute(text("ALTER TABLE characters ADD COLUMN source_range VARCHAR"))
                print("已添加 source_range 字段")
            
            # 添加最后解析时间字段
            if 'last_parsed_at' not in columns:
                conn.execute(text("ALTER TABLE characters ADD COLUMN last_parsed_at TIMESTAMP WITH TIME ZONE"))
                print("已添加 last_parsed_at 字段")
            
            conn.commit()
            print("字段添加成功！")
            
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
            # SQLite中删除列需要重建表，这里只给出警告
            print("请考虑以下方案：")
            print("1. 备份数据后重建characters表")
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