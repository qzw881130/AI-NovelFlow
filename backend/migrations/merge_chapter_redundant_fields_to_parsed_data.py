#!/usr/bin/env python3
"""
迁移脚本：合并章节冗余字段到 parsed_data

将 shot_images、shot_videos、character_images、transition_videos 数据
合并到 parsed_data JSON 字段中，消除数据冗余。

迁移后：
- shot_images[] -> parsed_data.shots[].image_url
- shot_videos[] -> parsed_data.shots[].video_url
- character_images (保留，用于角色图片映射)
- transition_videos -> parsed_data.transition_videos

注意：此迁移不会删除原字段，保留字段以便回滚
"""
import sqlite3
import json
import os
from datetime import datetime

# 数据库路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "..", "novelflow.db")


def backup_database():
    """备份数据库"""
    import shutil
    backup_path = os.path.join(
        SCRIPT_DIR,
        f"../backups/novelflow_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    shutil.copy(DB_PATH, backup_path)
    print(f"✅ 数据库已备份到: {backup_path}")
    return backup_path


def migrate_chapter_data(chapter_id: str, parsed_data: dict, shot_images: list,
                         shot_videos: list, transition_videos: dict) -> dict:
    """
    合并章节冗余数据到 parsed_data

    Args:
        chapter_id: 章节 ID
        parsed_data: 当前 parsed_data
        shot_images: shot_images 列表
        shot_videos: shot_videos 列表
        transition_videos: transition_videos 字典

    Returns:
        更新后的 parsed_data
    """
    if not parsed_data:
        parsed_data = {}

    # 确保 shots 数组存在
    if "shots" not in parsed_data:
        parsed_data["shots"] = []

    # 合并 shot_images 到 shots[].image_url
    if shot_images:
        for i, image_url in enumerate(shot_images):
            if image_url:
                # 扩展 shots 数组以容纳该索引
                while len(parsed_data["shots"]) <= i:
                    parsed_data["shots"].append({})

                # 只在 parsed_data 中没有该字段时才更新（优先使用现有数据）
                if "image_url" not in parsed_data["shots"][i] or not parsed_data["shots"][i].get("image_url"):
                    parsed_data["shots"][i]["image_url"] = image_url
                    print(f"  章节章节 {chapter_id}: shot[{i+1}].image_url <- {image_url}")

    # 合并 shot_videos 到 shots[].video_url
    if shot_videos:
        for i, video_url in enumerate(shot_videos):
            if video_url:
                # 扩展 shots 数组以容纳该索引
                while len(parsed_data["shots"]) <= i:
                    parsed_data["shots"].append({})

                # 只在 parsed_data 中没有该字段时才更新
                if "video_url" not in parsed_data["shots"][i] or not parsed_data["shots"][i].get("video_url"):
                    parsed_data["shots"][i]["video_url"] = video_url
                    print(f"  章节 {chapter_id}: shot[{i+1}].video_url <- {video_url}")

    # 合并 transition_videos
    if transition_videos:
        if "transition_videos" not in parsed_data:
            parsed_data["transition_videos"] = {}

        for key, url in transition_videos.items():
            if url and key not in parsed_data["transition_videos"]:
                parsed_data["transition_videos"][key] = url
                print(f"  章节 {chapter_id}: transition_videos[{key}] <- {url}")

    return parsed_data


def migrate():
    """执行迁移"""
    print("=" * 60)
    print("开始迁移：合并章节冗余字段到 parsed_data")
    print("=" * 60)

    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return

    # 备份数据库
    backup_path = backup_database()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 获取所有章节
        cursor.execute("""
            SELECT id, parsed_data, shot_images, shot_videos, transition_videos
            FROM chapters
        """)
        chapters = cursor.fetchall()

        print(f"\n找到 {len(chapters)} 个章节")

        migrated_count = 0
        skipped_count = 0

        for chapter in chapters:
            chapter_id = chapter[0]
            parsed_data_str = chapter[1]
            shot_images_str = chapter[2]
            shot_videos_str = chapter[3]
            transition_videos_str = chapter[4]

            # 解析现有数据
            parsed_data = json.loads(parsed_data_str) if parsed_data_str else {}
            shot_images = json.loads(shot_images_str) if shot_images_str else []
            shot_videos = json.loads(shot_videos_str) if shot_videos_str else []
            transition_videos = json.loads(transition_videos_str) if transition_videos_str else {}

            # 检查是否有需要迁移的数据
            has_shot_images = any(shot_images)
            has_shot_videos = any(shot_videos)
            has_transition_videos = bool(transition_videos)

            if not (has_shot_images or has_shot_videos or has_transition_videos):
                skipped_count += 1
                continue

            print(f"\n处理章节 {chapter_id}...")
            print(f"  shot_images: {len([x for x in shot_images if x])} 个")
            print(f"  shot_videos: {len([x for x in shot_videos if x])} 个")
            print(f"  transition_videos: {len(transition_videos)} 个")

            # 合并数据
            updated_parsed_data = migrate_chapter_data(
                chapter_id, parsed_data, shot_images, shot_videos, transition_videos
            )

            # 更新数据库
            updated_parsed_data_str = json.dumps(updated_parsed_data, ensure_ascii=False)
            cursor.execute("""
                UPDATE chapters
                SET parsed_data = ?
                WHERE id = ?
            """, (updated_parsed_data_str, chapter_id))

            migrated_count += 1

        conn.commit()

        print("\n" + "=" * 60)
        print("迁移结果:")
        print(f"  - 已迁移章节: {migrated_count}")
        print(f"  - 跳过章节（无冗余数据）: {skipped_count}")
        print(f"  - 备份文件: {backup_path}")
        print("=" * 60)
        print("\n✅ 迁移完成")
        print("\n注意: 原字段 (shot_images, shot_videos, transition_videos) 已保留，")
        print("      后续版本将移除这些字段的使用，但数据仍可用于回滚。")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ 迁移失败: {e}")
        print(f"可以从备份恢复: {backup_path}")
        raise
    finally:
        conn.close()


def rollback(backup_path: str = None):
    """
    从备份恢复数据

    Args:
        backup_path: 备份文件路径，如果为 None 则查找最新备份
    """
    import shutil

    if backup_path is None:
        # 查找最新备份
        backup_dir = os.path.join(SCRIPT_DIR, "../backups")
        if os.path.exists(backup_dir):
            backups = sorted([f for f in os.listdir(backup_dir) if f.startswith("novelflow_backup_")])
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

    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        backup_path = sys.argv[2] if len(sys.argv) > 2 else None
        rollback(backup_path)
    else:
        migrate()