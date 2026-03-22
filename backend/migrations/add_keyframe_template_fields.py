"""
添加关键帧提示词模板字段到小说表

为小说添加 keyframe_description_prompt_template_id 字段，支持小说级别配置关键帧描述提示词模板
"""

import sqlite3
import os

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'novelflow.db')


def migrate():
    """执行迁移"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 检查列是否已存在
        cursor.execute("PRAGMA table_info(novels)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'keyframe_description_prompt_template_id' not in columns:
            print("添加 keyframe_description_prompt_template_id 列到 novels 表...")
            cursor.execute("""
                ALTER TABLE novels
                ADD COLUMN keyframe_description_prompt_template_id VARCHAR
            """)
            conn.commit()
            print("迁移完成：keyframe_description_prompt_template_id 列已添加")
        else:
            print("keyframe_description_prompt_template_id 列已存在，跳过迁移")

    except Exception as e:
        print(f"迁移失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()