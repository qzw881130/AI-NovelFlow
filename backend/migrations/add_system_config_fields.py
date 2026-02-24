"""
迁移脚本：添加 system_configs 表缺失的字段
运行: cd backend && python migrations/add_system_config_fields.py
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
        # 检查并添加 llm_max_tokens 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN llm_max_tokens INTEGER"))
            print("✓ Added llm_max_tokens column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ llm_max_tokens column already exists")
            else:
                print(f"✗ Error adding llm_max_tokens: {e}")
        
        # 检查并添加 llm_temperature 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN llm_temperature VARCHAR"))
            print("✓ Added llm_temperature column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ llm_temperature column already exists")
            else:
                print(f"✗ Error adding llm_temperature: {e}")
        
        # 检查并添加 proxy_enabled 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN proxy_enabled BOOLEAN DEFAULT 0"))
            print("✓ Added proxy_enabled column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ proxy_enabled column already exists")
            else:
                print(f"✗ Error adding proxy_enabled: {e}")
        
        # 检查并添加 http_proxy 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN http_proxy VARCHAR"))
            print("✓ Added http_proxy column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ http_proxy column already exists")
            else:
                print(f"✗ Error adding http_proxy: {e}")
        
        # 检查并添加 https_proxy 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN https_proxy VARCHAR"))
            print("✓ Added https_proxy column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ https_proxy column already exists")
            else:
                print(f"✗ Error adding https_proxy: {e}")
        
        # 检查并添加 output_resolution 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN output_resolution VARCHAR DEFAULT '1920x1080'"))
            print("✓ Added output_resolution column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ output_resolution column already exists")
            else:
                print(f"✗ Error adding output_resolution: {e}")
        
        # 检查并添加 output_frame_rate 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN output_frame_rate INTEGER DEFAULT 24"))
            print("✓ Added output_frame_rate column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ output_frame_rate column already exists")
            else:
                print(f"✗ Error adding output_frame_rate: {e}")
        
        # 检查并添加 parse_characters_prompt 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN parse_characters_prompt TEXT"))
            print("✓ Added parse_characters_prompt column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ parse_characters_prompt column already exists")
            else:
                print(f"✗ Error adding parse_characters_prompt: {e}")
        
        # 检查并添加 language 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN language VARCHAR DEFAULT 'zh-CN'"))
            print("✓ Added language column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ language column already exists")
            else:
                print(f"✗ Error adding language: {e}")
        
        # 检查并添加 timezone 列
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN timezone VARCHAR DEFAULT 'Asia/Shanghai'"))
            print("✓ Added timezone column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ timezone column already exists")
            else:
                print(f"✗ Error adding timezone: {e}")
        
        # 检查并添加 comfyui_host 列（如果不存在）
        try:
            conn.execute(text("ALTER TABLE system_configs ADD COLUMN comfyui_host VARCHAR DEFAULT 'http://localhost:8188'"))
            print("✓ Added comfyui_host column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ comfyui_host column already exists")
            else:
                print(f"✗ Error adding comfyui_host: {e}")
        
        conn.commit()
    
    # 为已有数据设置默认值
    print("\n📝 初始化历史数据...")
    with engine.connect() as conn:
        # 为 llm_max_tokens 为 NULL 的记录设置默认值 4000
        try:
            result = conn.execute(text(
                "UPDATE system_configs SET llm_max_tokens = 4000 WHERE llm_max_tokens IS NULL"
            ))
            print(f"✓ Set default llm_max_tokens=4000 for {result.rowcount} records")
        except Exception as e:
            print(f"✗ Error setting default llm_max_tokens: {e}")
        
        # 为 llm_temperature 为 NULL 的记录设置默认值 0.7
        try:
            result = conn.execute(text(
                "UPDATE system_configs SET llm_temperature = '0.7' WHERE llm_temperature IS NULL"
            ))
            print(f"✓ Set default llm_temperature=0.7 for {result.rowcount} records")
        except Exception as e:
            print(f"✗ Error setting default llm_temperature: {e}")
        
        # 为其他可能为空的字段设置默认值
        try:
            conn.execute(text(
                "UPDATE system_configs SET output_resolution = '1920x1080' WHERE output_resolution IS NULL"
            ))
            conn.execute(text(
                "UPDATE system_configs SET output_frame_rate = 24 WHERE output_frame_rate IS NULL"
            ))
            conn.execute(text(
                "UPDATE system_configs SET language = 'zh-CN' WHERE language IS NULL"
            ))
            conn.execute(text(
                "UPDATE system_configs SET timezone = 'Asia/Shanghai' WHERE timezone IS NULL"
            ))
            conn.execute(text(
                "UPDATE system_configs SET comfyui_host = 'http://localhost:8188' WHERE comfyui_host IS NULL"
            ))
            print("✓ Set other default values for NULL fields")
        except Exception as e:
            print(f"✗ Error setting other default values: {e}")
        
        conn.commit()
    
    print("\n✅ Migration completed!")

if __name__ == "__main__":
    migrate()
