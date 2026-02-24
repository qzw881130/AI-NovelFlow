#!/usr/bin/env python3
"""
更新转场工作流描述为"适合"说明
"""
import sqlite3
import os

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), "novelflow.db")

def update():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 定义新的描述映射
    updates = [
        {
            "name": "LTX2 镜头转场视频",
            "old_desc": "LTX-2 镜头转场（最稳：不改世界，只改镜头）",
            "new_desc": "适合：首尾帧是同一场景不同景别/角度"
        },
        {
            "name": "LTX2 光线转场视频",
            "old_desc": "LTX-2 光线/时间转场（白天到夜晚/室内灯亮）",
            "new_desc": "适合：首尾帧颜色差很多，但场景/人物不变"
        },
        {
            "name": "LTX2 遮挡转场视频",
            "old_desc": "LTX-2 遮挡转场（wipe/遮挡物经过镜头）",
            "new_desc": "适合：两张图差异大，想自然衔接"
        }
    ]
    
    updated_count = 0
    
    for update_info in updates:
        # 先查找匹配的工作流
        cursor.execute(
            "SELECT id, name, description FROM workflows WHERE name = ?",
            (update_info["name"],)
        )
        workflow = cursor.fetchone()
        
        if workflow:
            print(f"找到: {workflow[1]}")
            print(f"  当前描述: {workflow[2]}")
            
            # 更新描述
            cursor.execute(
                "UPDATE workflows SET description = ? WHERE id = ?",
                (update_info["new_desc"], workflow[0])
            )
            print(f"  新描述: {update_info['new_desc']}")
            updated_count += 1
        else:
            print(f"未找到: {update_info['name']}")
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ 已更新 {updated_count} 个工作流描述")

if __name__ == "__main__":
    update()
