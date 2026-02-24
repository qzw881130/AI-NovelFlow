"""
添加 node_mapping 字段到 workflows 表
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "novelflow.db")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(workflows)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "node_mapping" not in columns:
        print("Adding node_mapping column to workflows table...")
        cursor.execute("ALTER TABLE workflows ADD COLUMN node_mapping TEXT")
        conn.commit()
        print("✓ Migration completed!")
    else:
        print("Column node_mapping already exists.")
    
    conn.close()

if __name__ == "__main__":
    migrate()
