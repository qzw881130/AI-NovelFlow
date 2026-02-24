"""
迁移脚本：为 llm_logs 表添加 duration 字段
运行: cd backend && python migrations/add_llm_logs_duration.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

DATABASE_URL = "sqlite:///./novelflow.db"

def migrate():
    """添加 duration 列到 llm_logs 表"""
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        try:
            # 检查字段是否已存在
            result = conn.execute(text("PRAGMA table_info(llm_logs)"))
            columns = [row[1] for row in result.fetchall()]
            
            if 'duration' not in columns:
                conn.execute(text("ALTER TABLE llm_logs ADD COLUMN duration REAL"))
                print("✓ Added duration column to llm_logs table")
            else:
                print("✓ duration column already exists")
            
            conn.commit()
        except Exception as e:
            print(f"✗ Error: {e}")
            conn.rollback()
    
    print("\n✅ Migration completed!")

if __name__ == "__main__":
    migrate()
