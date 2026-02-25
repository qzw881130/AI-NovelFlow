"""
Task Repository 层

封装任务相关的数据库查询逻辑
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.task import Task


class TaskRepository:
    """任务数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_all(self, limit: int = 50) -> List[Task]:
        """获取所有任务（按创建时间倒序）"""
        return self.db.query(Task).order_by(Task.created_at.desc()).limit(limit).all()
    
    def list_by_status(self, status: str, limit: int = 50) -> List[Task]:
        """按状态获取任务列表"""
        return self.db.query(Task).filter(
            Task.status == status
        ).order_by(Task.created_at.desc()).limit(limit).all()
    
    def list_by_type(self, task_type: str, limit: int = 50) -> List[Task]:
        """按类型获取任务列表"""
        return self.db.query(Task).filter(
            Task.type == task_type
        ).order_by(Task.created_at.desc()).limit(limit).all()
    
    def list_by_filters(
        self, 
        status: Optional[str] = None, 
        task_type: Optional[str] = None, 
        limit: int = 50
    ) -> List[Task]:
        """按筛选条件获取任务列表"""
        query = self.db.query(Task).order_by(Task.created_at.desc())
        
        if status:
            query = query.filter(Task.status == status)
        if task_type:
            query = query.filter(Task.type == task_type)
        
        return query.limit(limit).all()
    
    def get_by_id(self, task_id: str) -> Optional[Task]:
        """根据 ID 获取任务"""
        return self.db.query(Task).filter(Task.id == task_id).first()
    
    def get_active_by_character(self, character_id: str) -> Optional[Task]:
        """获取角色进行中的任务"""
        return self.db.query(Task).filter(
            Task.character_id == character_id,
            Task.type == "character_portrait",
            Task.status.in_(["pending", "running"])
        ).first()
    
    def get_active_by_scene(self, scene_id: str) -> Optional[Task]:
        """获取场景进行中的任务"""
        return self.db.query(Task).filter(
            Task.scene_id == scene_id,
            Task.type == "scene_image",
            Task.status.in_(["pending", "running"])
        ).first()
    
    def get_active_by_chapter_shot(
        self, 
        novel_id: str, 
        chapter_id: str, 
        shot_index: int
    ) -> Optional[Task]:
        """获取分镜进行中的任务"""
        return self.db.query(Task).filter(
            Task.novel_id == novel_id,
            Task.chapter_id == chapter_id,
            Task.type == "shot_image",
            Task.name.like(f"%镜{shot_index}%"),
            Task.status.in_(["pending", "running"])
        ).first()
    
    def list_active_tasks(self) -> List[Task]:
        """获取所有进行中或待处理的任务"""
        return self.db.query(Task).filter(
            Task.status.in_(["pending", "running"])
        ).all()
    
    def create(self, task: Task) -> Task:
        """创建任务"""
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task
    
    def update(self, task: Task) -> Task:
        """更新任务"""
        self.db.commit()
        self.db.refresh(task)
        return task
    
    def delete(self, task: Task) -> None:
        """删除任务"""
        self.db.delete(task)
        self.db.commit()
    
    def batch_update_status(
        self, 
        tasks: List[Task], 
        status: str, 
        error_message: str = None
    ) -> int:
        """批量更新任务状态"""
        count = 0
        for task in tasks:
            task.status = status
            if error_message:
                task.error_message = error_message
            count += 1
        self.db.commit()
        return count
    
    def get_by_novel(self, novel_id: str) -> List[Task]:
        """获取小说的所有任务"""
        return self.db.query(Task).filter(
            Task.novel_id == novel_id
        ).order_by(Task.created_at.desc()).all()
    
    def get_by_chapter(self, chapter_id: str) -> List[Task]:
        """获取章节的所有任务"""
        return self.db.query(Task).filter(
            Task.chapter_id == chapter_id
        ).order_by(Task.created_at.desc()).all()
    
    def get_by_character(self, character_id: str) -> List[Task]:
        """获取角色的所有任务"""
        return self.db.query(Task).filter(
            Task.character_id == character_id
        ).order_by(Task.created_at.desc()).all()
    
    def get_by_scene(self, scene_id: str) -> List[Task]:
        """获取场景的所有任务"""
        return self.db.query(Task).filter(
            Task.scene_id == scene_id
        ).order_by(Task.created_at.desc()).all()
    
    def list_with_relations(
        self, 
        status: Optional[str] = None, 
        task_type: Optional[str] = None, 
        limit: int = 50
    ) -> tuple:
        """
        获取任务列表及其关联数据
        
        Returns:
            (tasks, novel_ids, chapter_ids, workflow_ids) 用于批量查询关联数据
        """
        tasks = self.list_by_filters(status=status, task_type=task_type, limit=limit)
        
        novel_ids = {t.novel_id for t in tasks if t.novel_id}
        chapter_ids = {t.chapter_id for t in tasks if t.chapter_id}
        workflow_ids = {t.workflow_id for t in tasks if t.workflow_id}
        
        return tasks, novel_ids, chapter_ids, workflow_ids
