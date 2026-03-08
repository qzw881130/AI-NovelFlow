#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迁移脚本：将 parsed_data.shots 迁移到独立的 shots 表

此迁移完成以下任务：
1. 创建 shots 表（如果不存在）
2. 从 chapters.parsed_data.shots 提取分镜数据，创建 Shot 记录
3. 从 chapters 冗余字段回填图片/视频状态
4. 迁移后从 parsed_data 中移除 shots 数组（保留原数据用于回滚）

运行方式：
    python migrations/migrate_shots_to_separate_table.py          # 执行迁移
    python migrations/migrate_shots_to_separate_table.py rollback # 回滚迁移
    python migrations/migrate_shots_to_separate_table.py check    # 检查迁移状态
"""
import sqlite3
import json
import os
import sys
import uuid
from datetime import datetime

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 数据库路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "..", "novelflow.db")


def generate_uuid():
    return str(uuid.uuid4())


def backup_database():
    """备份数据库"""
    import shutil
    backup_path = os.path.join(
        SCRIPT_DIR,
        f"../backups/novelflow_backup_shots_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    shutil.copy(DB_PATH, backup_path)
    print(f"✅ 数据库已备份到: {backup_path}")
    return backup_path


def create_shots_table(conn):
    """创建 shots 表"""
    cursor = conn.cursor()

    # 检查表是否存在
    cursor.execute("""
        SELECT name FROM sqlite_master WHERE type='table' AND name='shots'
    """)
    if cursor.fetchone():
        print("  shots 表已存在")
        return

    # 创建 shots 表 (使用 "index" 加引号避免保留字冲突)
    cursor.execute("""
        CREATE TABLE shots (
            id VARCHAR PRIMARY KEY,
            chapter_id VARCHAR NOT NULL,
            "index" INTEGER NOT NULL,
            description TEXT DEFAULT '',
            characters TEXT DEFAULT '[]',
            scene VARCHAR DEFAULT '',
            props TEXT DEFAULT '[]',
            duration INTEGER DEFAULT 4,
            image_url VARCHAR,
            image_path VARCHAR,
            image_status VARCHAR DEFAULT 'pending',
            image_task_id VARCHAR,
            video_url VARCHAR,
            video_status VARCHAR DEFAULT 'pending',
            video_task_id VARCHAR,
            merged_character_image VARCHAR,
            dialogues TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (chapter_id) REFERENCES chapters(id)
        )
    """)

    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_shots_chapter_id ON shots(chapter_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_shots_index ON shots(\"index\")")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_shots_image_status ON shots(image_status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_shots_video_status ON shots(video_status)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_shots_chapter_index ON shots(chapter_id, \"index\")")

    conn.commit()
    print("  ✅ shots 表创建成功")


def migrate_shots_data(conn):
    """迁移分镜数据"""
    cursor = conn.cursor()

    # 获取所有章节
    cursor.execute("""
        SELECT id, parsed_data, shot_images, shot_videos
        FROM chapters
        WHERE parsed_data IS NOT NULL
    """)
    chapters = cursor.fetchall()

    print(f"\n找到 {len(chapters)} 个章节需要检查")

    migrated_shots = 0
    skipped_chapters = 0

    for chapter in chapters:
        chapter_id = chapter[0]
        parsed_data_str = chapter[1]
        shot_images_str = chapter[2]
        shot_videos_str = chapter[3]

        parsed_data = json.loads(parsed_data_str) if parsed_data_str else {}
        shots_data = parsed_data.get("shots", [])

        if not shots_data:
            skipped_chapters += 1
            continue

        # 解析冗余字段用于回填状态
        shot_images = json.loads(shot_images_str) if shot_images_str else []
        shot_videos = json.loads(shot_videos_str) if shot_videos_str else []

        print(f"\n  处理章节 {chapter_id}: {len(shots_data)} 个分镜")

        for idx, shot_data in enumerate(shots_data, 1):
            # 检查是否已存在
            cursor.execute("""
                SELECT id FROM shots WHERE chapter_id = ? AND "index" = ?
            """, (chapter_id, idx))
            if cursor.fetchone():
                print(f"    分镜 {idx} 已存在，跳过")
                continue

            # 提取图片和视频 URL
            image_url = shot_data.get("image_url")
            video_url = shot_data.get("video_url")

            # 从冗余字段回填（如果 parsed_data 中没有）
            if not image_url and idx <= len(shot_images) and shot_images[idx - 1]:
                image_url = shot_images[idx - 1]
            if not video_url and idx <= len(shot_videos) and shot_videos[idx - 1]:
                video_url = shot_videos[idx - 1]

            # 确定状态
            image_status = "completed" if image_url else "pending"
            video_status = "completed" if video_url else "pending"

            # 创建 Shot 记录
            shot_id = generate_uuid()
            cursor.execute("""
                INSERT INTO shots (
                    id, chapter_id, "index", description, characters, scene, props, duration,
                    image_url, image_path, image_status, image_task_id,
                    video_url, video_status, video_task_id,
                    merged_character_image, dialogues
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                shot_id,
                chapter_id,
                idx,
                shot_data.get("description", ""),
                json.dumps(shot_data.get("characters", []), ensure_ascii=False),
                shot_data.get("scene", ""),
                json.dumps(shot_data.get("props", []), ensure_ascii=False),
                shot_data.get("duration", 4),
                image_url,
                shot_data.get("image_path"),
                image_status,
                shot_data.get("image_task_id"),
                video_url,
                video_status,
                shot_data.get("video_task_id"),
                shot_data.get("merged_character_image"),
                json.dumps(shot_data.get("dialogues", []), ensure_ascii=False)
            ))

            migrated_shots += 1
            print(f"    ✅ 分镜 {idx}: {shot_id[:8]}... (image: {image_status}, video: {video_status})")

    conn.commit()
    return migrated_shots, skipped_chapters


def remove_shots_from_parsed_data(conn):
    """从 parsed_data 中移除 shots 数组（保留原字段用于回滚）"""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, parsed_data FROM chapters WHERE parsed_data IS NOT NULL
    """)
    chapters = cursor.fetchall()

    updated_count = 0

    for chapter_id, parsed_data_str in chapters:
        parsed_data = json.loads(parsed_data_str) if parsed_data_str else {}

        if "shots" not in parsed_data:
            continue

        # 移除 shots 数组
        parsed_data.pop("shots", None)

        # 更新数据库
        cursor.execute("""
            UPDATE chapters SET parsed_data = ? WHERE id = ?
        """, (json.dumps(parsed_data, ensure_ascii=False), chapter_id))

        updated_count += 1

    conn.commit()
    return updated_count


def check_migration_status():
    """检查迁移状态"""
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 检查 shots 表
    cursor.execute("""
        SELECT name FROM sqlite_master WHERE type='table' AND name='shots'
    """)
    table_exists = cursor.fetchone() is not None

    if not table_exists:
        print("❌ shots 表不存在，需要执行迁移")
        conn.close()
        return

    # 统计 shots 数量
    cursor.execute("SELECT COUNT(*) FROM shots")
    shots_count = cursor.fetchone()[0]

    # 检查 parsed_data 中还有 shots 的章节数
    cursor.execute("""
        SELECT COUNT(*) FROM chapters
        WHERE parsed_data IS NOT NULL AND parsed_data LIKE '%"shots"%'
    """)
    chapters_with_shots = cursor.fetchone()[0]

    print("=" * 60)
    print("迁移状态检查")
    print("=" * 60)
    print(f"  shots 表记录数: {shots_count}")
    print(f"  parsed_data 中仍包含 shots 的章节数: {chapters_with_shots}")

    if chapters_with_shots > 0:
        print("\n⚠️  存在未迁移的章节数据，建议重新运行迁移")
    else:
        print("\n✅ 所有分镜数据已迁移完成")

    # 显示最近的分镜
    cursor.execute("""
        SELECT id, chapter_id, "index", image_status, video_status
        FROM shots
        ORDER BY created_at DESC
        LIMIT 5
    """)
    recent_shots = cursor.fetchall()

    if recent_shots:
        print("\n最近迁移的分镜:")
        print("-" * 60)
        for shot in recent_shots:
            print(f"  分镜 {shot[2]} (章节 {shot[1][:8]}...): image={shot[3]}, video={shot[4]}")

    conn.close()


def migrate():
    """执行迁移"""
    print("=" * 60)
    print("开始迁移：将 parsed_data.shots 迁移到独立的 shots 表")
    print("=" * 60)

    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return

    # 备份数据库
    backup_path = backup_database()

    conn = sqlite3.connect(DB_PATH)

    try:
        # 步骤 1: 创建 shots 表
        print("\n步骤 1: 创建 shots 表")
        create_shots_table(conn)

        # 步骤 2: 迁移分镜数据
        print("\n步骤 2: 迁移分镜数据")
        migrated_shots, skipped_chapters = migrate_shots_data(conn)

        # 步骤 3: 从 parsed_data 移除 shots
        print("\n步骤 3: 从 parsed_data 移除 shots 数组")
        updated_chapters = remove_shots_from_parsed_data(conn)

        print("\n" + "=" * 60)
        print("迁移结果:")
        print(f"  - 迁移的分镜数: {migrated_shots}")
        print(f"  - 跳过的章节数: {skipped_chapters}")
        print(f"  - 更新的章节数: {updated_chapters}")
        print(f"  - 备份文件: {backup_path}")
        print("=" * 60)
        print("\n✅ 迁移完成")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ 迁移失败: {e}")
        print(f"可以从备份恢复: {backup_path}")
        raise
    finally:
        conn.close()


def rollback(backup_path: str = None):
    """从备份恢复数据"""
    import shutil

    if backup_path is None:
        # 查找最新备份
        backup_dir = os.path.join(SCRIPT_DIR, "../backups")
        if os.path.exists(backup_dir):
            backups = sorted([f for f in os.listdir(backup_dir) if f.startswith("novelflow_backup_shots_")])
            if backups:
                backup_path = os.path.join(backup_dir, backups[-1])
            else:
                print("❌ 未找到备份文件")
                return
        else:
            print("❌ 备份目录不存在")
            return

    if not os.path.exists(backup_path):
        print(f"❌ 备份文件不存在: {backup_path}")
        return

    shutil.copy(backup_path, DB_PATH)
    print(f"✅ 已从备份恢复: {backup_path}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "rollback":
            backup_path = sys.argv[2] if len(sys.argv) > 2 else None
            rollback(backup_path)
        elif sys.argv[1] == "check":
            check_migration_status()
        else:
            print(f"未知命令: {sys.argv[1]}")
            print("用法:")
            print("  python migrations/migrate_shots_to_separate_table.py          # 执行迁移")
            print("  python migrations/migrate_shots_to_separate_table.py rollback # 回滚迁移")
            print("  python migrations/migrate_shots_to_separate_table.py check    # 检查状态")
    else:
        migrate()