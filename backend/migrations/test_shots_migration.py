#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迁移测试脚本：验证 shots 数据迁移的正确性

此脚本验证以下内容：
1. shots 表是否正确创建
2. 分镜数据是否完整迁移
3. 冗余字段数据是否正确回填
4. parsed_data 中 shots 数组是否已移除
5. 数据一致性检查

运行方式：
    python migrations/test_shots_migration.py          # 运行所有测试
    python migrations/test_shots_migration.py --verbose # 详细输出
"""
import sqlite3
import json
import os
import sys

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 数据库路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "..", "novelflow.db")


class MigrationTest:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.passed = 0
        self.failed = 0
        self.conn = None

    def log(self, msg, level="info"):
        if level == "error":
            print(f"  ❌ {msg}")
        elif level == "success":
            print(f"  ✅ {msg}")
        elif self.verbose:
            print(f"  ℹ️  {msg}")

    def test_shots_table_exists(self):
        """测试 shots 表是否存在"""
        print("\n[测试 1] shots 表是否存在")

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master WHERE type='table' AND name='shots'
        """)
        result = cursor.fetchone()

        if result:
            self.log("shots 表存在", "success")
            self.passed += 1
            return True
        else:
            self.log("shots 表不存在", "error")
            self.failed += 1
            return False

    def test_shots_indexes(self):
        """测试索引是否正确创建"""
        print("\n[测试 2] shots 表索引")

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND tbl_name='shots'
        """)
        indexes = [row[0] for row in cursor.fetchall()]

        expected_indexes = [
            'ix_shots_chapter_id',
            'ix_shots_index',
            'ix_shots_image_status',
            'ix_shots_video_status',
            'ix_shots_chapter_index'
        ]

        all_present = True
        for idx_name in expected_indexes:
            if idx_name in indexes:
                self.log(f"索引 {idx_name} 存在", "success")
            else:
                self.log(f"索引 {idx_name} 缺失", "error")
                all_present = False

        if all_present:
            self.passed += 1
        else:
            self.failed += 1

        return all_present

    def test_shots_data_integrity(self):
        """测试分镜数据完整性"""
        print("\n[测试 3] 分镜数据完整性")

        cursor = self.conn.cursor()

        # 获取所有有分镜的章节
        cursor.execute("""
            SELECT id, parsed_data FROM chapters WHERE parsed_data IS NOT NULL
        """)
        chapters = cursor.fetchall()

        total_original_shots = 0
        total_migrated_shots = 0
        integrity_issues = []

        for chapter_id, parsed_data_str in chapters:
            parsed_data = json.loads(parsed_data_str) if parsed_data_str else {}

            # 统计原始分镜数（如果在备份中存在）
            original_shots = parsed_data.get("_original_shots", [])
            if original_shots:
                total_original_shots += len(original_shots)

            # 统计迁移后的分镜数
            cursor.execute("""
                SELECT COUNT(*) FROM shots WHERE chapter_id = ?
            """, (chapter_id,))
            migrated_count = cursor.fetchone()[0]
            total_migrated_shots += migrated_count

            if original_shots and len(original_shots) != migrated_count:
                integrity_issues.append(
                    f"章节 {chapter_id[:8]}... 原始 {len(original_shots)} 个，迁移 {migrated_count} 个"
                )

        self.log(f"总迁移分镜数: {total_migrated_shots}")

        if integrity_issues:
            self.log("发现数据不一致:", "error")
            for issue in integrity_issues:
                self.log(f"  {issue}", "error")
            self.failed += 1
            return False
        else:
            self.log("所有分镜数据完整迁移", "success")
            self.passed += 1
            return True

    def test_redundant_fields_backfill(self):
        """测试冗余字段数据回填"""
        print("\n[测试 4] 冗余字段数据回填")

        cursor = self.conn.cursor()

        # 获取所有章节及其冗余字段
        cursor.execute("""
            SELECT id, shot_images, shot_videos
            FROM chapters
            WHERE shot_images IS NOT NULL OR shot_videos IS NOT NULL
        """)
        chapters = cursor.fetchall()

        backfill_issues = []

        for chapter_id, shot_images_str, shot_videos_str in chapters:
            shot_images = json.loads(shot_images_str) if shot_images_str else []
            shot_videos = json.loads(shot_videos_str) if shot_videos_str else []

            if not shot_images and not shot_videos:
                continue

            # 获取该章节的分镜
            cursor.execute("""
                SELECT index, image_url, video_url, image_status, video_status
                FROM shots WHERE chapter_id = ? ORDER BY index
            """, (chapter_id,))
            shots = cursor.fetchall()

            for shot in shots:
                idx = shot[0]  # index is 1-based
                image_url = shot[1]
                video_url = shot[2]
                image_status = shot[3]
                video_status = shot[4]

                # 检查图片回填
                if idx <= len(shot_images) and shot_images[idx - 1]:
                    if not image_url and image_status == "pending":
                        backfill_issues.append(
                            f"章节 {chapter_id[:8]}... 分镜 {idx}: 冗余图片未回填"
                        )

                # 检查视频回填
                if idx <= len(shot_videos) and shot_videos[idx - 1]:
                    if not video_url and video_status == "pending":
                        backfill_issues.append(
                            f"章节 {chapter_id[:8]}... 分镜 {idx}: 冗余视频未回填"
                        )

        if backfill_issues:
            self.log("发现回填问题:", "error")
            for issue in backfill_issues[:10]:  # 只显示前10个
                self.log(f"  {issue}", "error")
            if len(backfill_issues) > 10:
                self.log(f"  ... 还有 {len(backfill_issues) - 10} 个问题")
            self.failed += 1
            return False
        else:
            self.log("冗余字段数据已正确回填", "success")
            self.passed += 1
            return True

    def test_parsed_data_shots_removed(self):
        """测试 parsed_data 中 shots 数组是否已移除"""
        print("\n[测试 5] parsed_data 中 shots 数组移除")

        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM chapters
            WHERE parsed_data IS NOT NULL AND parsed_data LIKE '%"shots"%'
        """)
        count = cursor.fetchone()[0]

        if count > 0:
            self.log(f"仍有 {count} 个章节的 parsed_data 包含 shots", "error")
            self.failed += 1
            return False
        else:
            self.log("所有 parsed_data 中的 shots 数组已移除", "success")
            self.passed += 1
            return True

    def test_shot_fields_validity(self):
        """测试分镜字段有效性"""
        print("\n[测试 6] 分镜字段有效性")

        cursor = self.conn.cursor()

        # 检查 JSON 字段是否有效
        cursor.execute("SELECT id, characters, props, dialogues FROM shots")
        shots = cursor.fetchall()

        invalid_json = []

        for shot_id, characters, props, dialogues in shots:
            for field_name, field_value in [('characters', characters), ('props', props), ('dialogues', dialogues)]:
                try:
                    if field_value:
                        json.loads(field_value)
                except json.JSONDecodeError:
                    invalid_json.append(f"分镜 {shot_id[:8]}... 字段 {field_name}")

        if invalid_json:
            self.log("发现无效 JSON 字段:", "error")
            for issue in invalid_json[:10]:
                self.log(f"  {issue}", "error")
            self.failed += 1
            return False
        else:
            self.log("所有 JSON 字段有效", "success")
            self.passed += 1
            return True

    def test_unique_constraint(self):
        """测试章节内分镜序号唯一性"""
        print("\n[测试 7] 分镜序号唯一性")

        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT chapter_id, "index", COUNT(*) as cnt
            FROM shots
            GROUP BY chapter_id, "index"
            HAVING COUNT(*) > 1
        """)
        duplicates = cursor.fetchall()

        if duplicates:
            self.log("发现重复的分镜序号:", "error")
            for chapter_id, idx, cnt in duplicates:
                self.log(f"  章节 {chapter_id[:8]}... 序号 {idx}: {cnt} 条记录", "error")
            self.failed += 1
            return False
        else:
            self.log("所有分镜序号唯一", "success")
            self.passed += 1
            return True

    def test_foreign_key_integrity(self):
        """测试外键完整性"""
        print("\n[测试 8] 外键完整性")

        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT s.id, s.chapter_id
            FROM shots s
            LEFT JOIN chapters c ON s.chapter_id = c.id
            WHERE c.id IS NULL
        """)
        orphan_shots = cursor.fetchall()

        if orphan_shots:
            self.log("发现孤立分镜（无对应章节）:", "error")
            for shot_id, chapter_id in orphan_shots[:10]:
                self.log(f"  分镜 {shot_id[:8]}... 引用不存在的章节 {chapter_id[:8]}...", "error")
            self.failed += 1
            return False
        else:
            self.log("所有外键关系有效", "success")
            self.passed += 1
            return True

    def run_all_tests(self):
        """运行所有测试"""
        print("=" * 60)
        print("Shots 迁移测试")
        print("=" * 60)

        if not os.path.exists(DB_PATH):
            print(f"\n❌ 数据库文件不存在: {DB_PATH}")
            return False

        self.conn = sqlite3.connect(DB_PATH)

        try:
            self.test_shots_table_exists()
            self.test_shots_indexes()
            self.test_shots_data_integrity()
            self.test_redundant_fields_backfill()
            self.test_parsed_data_shots_removed()
            self.test_shot_fields_validity()
            self.test_unique_constraint()
            self.test_foreign_key_integrity()
        finally:
            self.conn.close()

        print("\n" + "=" * 60)
        print(f"测试结果: {self.passed} 通过, {self.failed} 失败")
        print("=" * 60)

        if self.failed == 0:
            print("\n✅ 所有测试通过！迁移验证成功。")
            return True
        else:
            print(f"\n⚠️  有 {self.failed} 个测试失败，请检查迁移结果。")
            return False


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    tester = MigrationTest(verbose=verbose)
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()