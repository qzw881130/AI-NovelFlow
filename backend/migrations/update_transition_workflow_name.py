#!/usr/bin/env python3
"""
更新转场工作流名称：将"首尾帧转场"改为"遮挡转场"
"""
import sqlite3
import os

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), "novelflow.db")

def update():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 查找包含"首尾帧"的工作流
    cursor.execute("SELECT id, name, description FROM workflows WHERE name LIKE '%首尾帧%'")
    workflows = cursor.fetchall()
    
    if not workflows:
        print("没有找到包含'首尾帧'的工作流")
        # 检查是否有遮挡转场工作流
        cursor.execute("SELECT id, name, description FROM workflows WHERE name LIKE '%遮挡%'")
        workflows = cursor.fetchall()
        if workflows:
            print("已存在遮挡转场工作流:")
            for wf in workflows:
                print(f"  - {wf[1]}: {wf[2]}")
        conn.close()
        return
    
    print(f"找到 {len(workflows)} 个需要更新的工作流:")
    for wf in workflows:
        print(f"  - {wf[1]}: {wf[2]}")
    
    # 更新名称和描述
    cursor.execute("""
        UPDATE workflows 
        SET name = 'LTX2 遮挡转场视频',
            description = 'LTX-2 遮挡转场（wipe/遮挡物经过镜头）'
        WHERE name LIKE '%首尾帧%'
    """)
    
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    
    print(f"\n✅ 已更新 {updated} 个工作流")
    print("新名称: LTX2 遮挡转场视频")
    print("新描述: LTX-2 遮挡转场（wipe/遮挡物经过镜头）")

if __name__ == "__main__":
    update()
