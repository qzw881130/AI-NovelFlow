"""
迁移脚本：为 system_configs 表添加 llm_timeout 字段（LLM 请求超时，单位秒）
运行: cd backend && python migrations/add_llm_timeout_field.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

# 直接使用数据库 URL
DATABASE_URL = "sqlite:///./novelflow.db"


def migrate():
    """添加缺失的数据库列"""
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        # 检查并添加 llm_timeout 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN llm_timeout INTEGER"))
            print("✓ Added llm_timeout column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ llm_timeout column already exists")
            else:
                print(f"✗ Error adding llm_timeout: {e}")

        conn.commit()

    # 为已有数据设置默认值 1800 秒（30 分钟）
    print("\n📝 初始化历史数据...")
    with engine.connect() as conn:
        try:
            result = conn.execute(text(
                "UPDATE system_configs SET llm_timeout = 1800 WHERE llm_timeout IS NULL"
            ))
            print(f"✓ Set default llm_timeout=1800 for {result.rowcount} records")
        except Exception as e:
            print(f"✗ Error setting default llm_timeout: {e}")

        conn.commit()

    print("\n✅ Migration completed!")


if __name__ == "__main__":
    migrate()
