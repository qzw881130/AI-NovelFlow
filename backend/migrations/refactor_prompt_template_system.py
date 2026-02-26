#!/usr/bin/env python3
"""
数据库迁移脚本：重构提示词模板管理系统

变更内容：
1. novels 表添加新的提示词模板关联字段
   - style_prompt_template_id: 风格提示词模板
   - character_parse_prompt_template_id: 角色解析提示词模板
   - scene_parse_prompt_template_id: 场景解析提示词模板
   - scene_prompt_template_id: 场景生成提示词模板

2. prompt_templates 表的 style 字段保留（SQLite不支持DROP COLUMN）
   但不再使用，风格改为独立的模板类型

注意：SQLite 不支持 DROP COLUMN，style 字段保留但不再使用
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.core.database import engine
from sqlalchemy import text


def upgrade():
    """升级数据库结构"""
    print("开始迁移：重构提示词模板管理系统...")
    
    with engine.connect() as conn:
        try:
            # ==================== 1. novels 表添加新字段 ====================
            print("\n[1/2] 检查 novels 表字段...")
            
            result = conn.execute(text("PRAGMA table_info(novels)"))
            novels_columns = [row[1] for row in result.fetchall()]
            
            new_columns = [
                ("style_prompt_template_id", "TEXT DEFAULT NULL"),
                ("character_parse_prompt_template_id", "TEXT DEFAULT NULL"),
                ("scene_parse_prompt_template_id", "TEXT DEFAULT NULL"),
                ("scene_prompt_template_id", "TEXT DEFAULT NULL"),
            ]
            
            for col_name, col_def in new_columns:
                if col_name not in novels_columns:
                    conn.execute(text(f"ALTER TABLE novels ADD COLUMN {col_name} {col_def}"))
                    print(f"  - 已添加 novels.{col_name} 字段")
                else:
                    print(f"  - novels.{col_name} 字段已存在，跳过")
            
            conn.commit()
            
            # ==================== 2. 提示词模板类型更新 ====================
            print("\n[2/2] 更新提示词模板类型...")
            
            # 检查是否已有 style 类型的模板
            result = conn.execute(text(
                "SELECT COUNT(*) FROM prompt_templates WHERE type = 'style'"
            ))
            style_count = result.fetchone()[0]
            
            if style_count == 0:
                print("  - 创建默认风格提示词模板...")
                # 从现有的 character 模板中提取风格创建 style 模板
                result = conn.execute(text(
                    "SELECT id, name, style FROM prompt_templates WHERE type = 'character' AND is_system = 1 LIMIT 1"
                ))
                row = result.fetchone()
                
                if row and row[2]:  # 如果有 style 内容
                    # 创建默认风格模板
                    conn.execute(text("""
                        INSERT INTO prompt_templates (id, name, description, template, type, is_system, is_active)
                        VALUES (
                            lower(hex(randomblob(16))),
                            '默认风格',
                            '适用于大多数场景的默认风格描述',
                            :style_content,
                            'style',
                            1,
                            1
                        )
                    """), {"style_content": row[2]})
                    print("  - 已创建默认风格提示词模板")
                else:
                    # 创建一个空的默认风格模板
                    conn.execute(text("""
                        INSERT INTO prompt_templates (id, name, description, template, type, is_system, is_active)
                        VALUES (
                            lower(hex(randomblob(16))),
                            '默认风格',
                            '适用于大多数场景的默认风格描述',
                            'anime style, high quality, detailed, professional artwork',
                            'style',
                            1,
                            1
                        )
                    """))
                    print("  - 已创建默认风格提示词模板（使用默认值）")
            else:
                print(f"  - 已存在 {style_count} 个风格提示词模板，跳过创建")
            
            # 检查是否已有 character_parse 类型的模板
            result = conn.execute(text(
                "SELECT COUNT(*) FROM prompt_templates WHERE type = 'character_parse'"
            ))
            parse_count = result.fetchone()[0]
            
            if parse_count == 0:
                print("  - 创建角色解析提示词模板...")
                # 从全局配置迁移（如果有的话）
                conn.execute(text("""
                    INSERT INTO prompt_templates (id, name, description, template, type, is_system, is_active)
                    VALUES (
                        lower(hex(randomblob(16))),
                        '标准角色解析',
                        '适用于大多数小说的角色解析',
                        '请参考 DEFAULT_PARSE_CHARACTERS_PROMPT 常量',
                        'character_parse',
                        1,
                        1
                    )
                """))
                print("  - 已创建角色解析提示词模板")
            
            conn.commit()
            print("\n迁移完成！")
            
        except Exception as e:
            print(f"迁移出错: {e}")
            conn.rollback()
            raise


def downgrade():
    """回滚迁移（谨慎使用）"""
    print("警告：此操作将删除新增的字段，可能导致数据丢失！")
    response = input("确认要回滚吗？(y/N): ")
    if response.lower() != 'y':
        print("已取消回滚")
        return
    
    print("SQLite 不支持 DROP COLUMN，回滚操作需要重建表...")
    print("建议手动备份数据后重新初始化数据库")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="提示词模板管理系统重构迁移")
    parser.add_argument("--downgrade", action="store_true", help="回滚迁移")
    args = parser.parse_args()
    
    if args.downgrade:
        downgrade()
    else:
        upgrade()
