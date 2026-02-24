#!/usr/bin/env python3
"""
数据库迁移脚本：为PromptTemplate表添加style字段
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.core.database import engine
from sqlalchemy import text

def upgrade():
    """添加style字段到prompt_templates表"""
    
    print("正在为prompt_templates表添加style字段...")
    
    with engine.connect() as conn:
        try:
            # 检查字段是否已存在
            result = conn.execute(text("PRAGMA table_info(prompt_templates)"))
            columns = [row[1] for row in result.fetchall()]
            
            # 添加style字段
            if 'style' not in columns:
                conn.execute(text("ALTER TABLE prompt_templates ADD COLUMN style TEXT DEFAULT ''"))
                print("已添加 style 字段")
            else:
                print("style 字段已存在，跳过添加")
            
            conn.commit()
            print("迁移完成！")
            
        except Exception as e:
            print(f"添加字段时出错: {e}")
            conn.rollback()

def downgrade():
    """回滚字段更改（谨慎使用）"""
    print("警告：此操作将删除style字段，可能导致数据丢失！")
    response = input("确认要回滚吗？(y/N): ")
    if response.lower() != 'y':
        print("操作已取消")
        return
        
    print("注意：SQLite不支持直接删除列，请手动处理或重建表")
    print("建议：保留现有字段（不影响使用）")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "downgrade":
        downgrade()
    else:
        upgrade()
