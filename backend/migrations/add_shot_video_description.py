"""
为 shots 表添加 video_description 字段

用于存储视频生成专用的提示词，与分镜描述（description）分开。
"""
import sqlite3
from pathlib import Path

# 获取数据库路径
db_path = Path(__file__).parent.parent / "novelflow.db"

print(f"数据库路径：{db_path}")

if not db_path.exists():
    print(f"数据库文件不存在：{db_path}")
    exit(1)

# 连接数据库
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

try:
    # 添加 video_description 字段
    print("正在添加 video_description 字段...")
    cursor.execute("""
        ALTER TABLE shots ADD COLUMN video_description TEXT DEFAULT ""
    """)
    conn.commit()
    print("✓ 成功添加 video_description 字段到 shots 表")

    # 验证字段是否添加成功
    cursor.execute("PRAGMA table_info(shots)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]
    if "video_description" in column_names:
        print("✓ 验证通过：video_description 字段已存在")
    else:
        print("✗ 验证失败：video_description 字段未找到")

except Exception as e:
    print(f"执行出错：{e}")
    conn.rollback()
finally:
    conn.close()
