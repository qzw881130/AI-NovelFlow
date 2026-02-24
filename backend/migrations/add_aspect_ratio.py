"""
添加画面比例字段到 novels 表
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "novelflow.db")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 检查列是否存在
    cursor.execute("PRAGMA table_info(novels)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "aspect_ratio" not in columns:
        print("Adding aspect_ratio column to novels table...")
        cursor.execute("ALTER TABLE novels ADD COLUMN aspect_ratio VARCHAR DEFAULT '16:9'")
        conn.commit()
        print("✓ Migration completed!")
    else:
        print("Column aspect_ratio already exists, checking empty values...")
        # 更新空值为默认值
        cursor.execute("UPDATE novels SET aspect_ratio = '16:9' WHERE aspect_ratio IS NULL OR aspect_ratio = ''")
        conn.commit()
        print(f"✓ Updated {cursor.rowcount} rows with default value")
    
    conn.close()

if __name__ == "__main__":
    migrate()
