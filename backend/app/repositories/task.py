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

    def get_active_by_character_and_type(self, character_id: str, task_type: str) -> Optional[Task]:
        """获取角色指定类型的进行中任务"""
        return self.db.query(Task).filter(
            Task.character_id == character_id,
            Task.type == task_type,
            Task.status.in_(["pending", "running"])
        ).first()
    
    def get_active_by_scene(self, scene_id: str) -> Optional[Task]:
        """获取场景进行中的任务"""
        return self.db.query(Task).filter(
            Task.scene_id == scene_id,
            Task.type == "scene_image",
            Task.status.in_(["pending", "running"])
        ).first()
    
    def get_active_by_prop(self, prop_id: str) -> Optional[Task]:
        """获取道具进行中的任务"""
        return self.db.query(Task).filter(
            Task.prop_id == prop_id,
            Task.type == "prop_image",
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
    
    def get_active_shot_task(
        self, 
        novel_id: str, 
        chapter_id: str, 
        shot_index: int, 
        task_type: str = "shot_image"
    ) -> Optional[Task]:
        """获取分镜进行中的任务"""
        return self.db.query(Task).filter(
            Task.novel_id == novel_id,
            Task.chapter_id == chapter_id,
            Task.type == task_type,
            Task.name.like(f"%镜{shot_index}%"),
            Task.status.in_(["pending", "running"])
        ).first()
    
    def get_failed_shot_task(
        self, 
        novel_id: str, 
        chapter_id: str, 
        shot_index: int, 
        task_type: str = "shot_video"
    ) -> Optional[Task]:
        """获取失败的分镜任务"""
        return self.db.query(Task).filter(
            Task.novel_id == novel_id,
            Task.chapter_id == chapter_id,
            Task.type == task_type,
            Task.name.like(f"%镜{shot_index}%"),
            Task.status == "failed"
        ).first()
    
    def get_transition_task(
        self, 
        novel_id: str, 
        chapter_id: str, 
        from_index: int, 
        to_index: int
    ) -> Optional[Task]:
        """获取转场视频任务"""
        return self.db.query(Task).filter(
            Task.novel_id == novel_id,
            Task.chapter_id == chapter_id,
            Task.type == "transition_video",
            Task.name.like(f"%镜{from_index}-镜{to_index}%"),
            Task.status.in_(["pending", "running"])
        ).first()
    
    def create_shot_image_task(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        chapter_title: str,
        workflow_id: str,
        workflow_name: str,
        shot_id: str = None
    ) -> Task:
        """创建分镜图片生成任务"""
        task = Task(
            type="shot_image",
            name=f"生成分镜图: 镜{shot_index}",
            description=f"为章节 '{chapter_title}' 的分镜 {shot_index} 生成图片",
            novel_id=novel_id,
            chapter_id=chapter_id,
            shot_id=shot_id,
            status="pending",
            workflow_id=workflow_id,
            workflow_name=workflow_name
        )
        return self.create(task)

    def create_shot_video_task(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        shot_duration: int,
        chapter_title: str,
        workflow_id: str,
        workflow_name: str,
        shot_id: str = None
    ) -> Task:
        """创建分镜视频生成任务"""
        task = Task(
            type="shot_video",
            name=f"生成视频: 镜{shot_index}",
            description=f"为章节 '{chapter_title}' 的分镜 {shot_index} 生成视频 (时长: {shot_duration}s)",
            novel_id=novel_id,
            chapter_id=chapter_id,
            shot_id=shot_id,
            status="pending",
            workflow_id=workflow_id,
            workflow_name=workflow_name
        )
        return self.create(task)
    
    def create_transition_video_task(
        self,
        novel_id: str,
        chapter_id: str,
        from_index: int,
        to_index: int,
        chapter_title: str,
        workflow_id: str,
        workflow_name: str,
        frame_count: int = 49
    ) -> Task:
        """创建转场视频生成任务"""
        task = Task(
            type="transition_video",
            name=f"生成转场视频: 镜{from_index}→镜{to_index}",
            description=f"为章节 '{chapter_title}' 的分镜 {from_index} 到 {to_index} 生成转场过渡视频",
            novel_id=novel_id,
            chapter_id=chapter_id,
            status="pending",
            progress=0,
            current_step="等待处理",
            workflow_id=workflow_id,
            workflow_name=workflow_name
        )
        return self.create(task)

    def create_character_audio_task(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        character_id: str,
        character_name: str,
        text: str,
        chapter_title: str,
        workflow_id: str = None,
        workflow_name: str = None,
        shot_id: str = None
    ) -> Task:
        """创建角色台词音频生成任务"""
        task = Task(
            type="character_audio",
            name=f"生成台词音频: 镜{shot_index}-{character_name}",
            description=f"为章节 '{chapter_title}' 的分镜 {shot_index} 角色 '{character_name}' 生成台词音频: {text[:50]}{'...' if len(text) > 50 else ''}",
            novel_id=novel_id,
            chapter_id=chapter_id,
            shot_id=shot_id,
            character_id=character_id,
            status="pending",
            progress=0,
            current_step="等待处理",
            workflow_id=workflow_id,
            workflow_name=workflow_name
        )
        return self.create(task)

    def get_active_character_audio_task(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        character_name: str
    ) -> Optional[Task]:
        """获取角色台词音频进行中的任务"""
        return self.db.query(Task).filter(
            Task.novel_id == novel_id,
            Task.chapter_id == chapter_id,
            Task.type == "character_audio",
            Task.name.like(f"%镜{shot_index}-{character_name}%"),
            Task.status.in_(["pending", "running"])
        ).first()

    def create_narrator_audio_task(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        character_id: str,
        text: str,
        chapter_title: str,
        workflow_id: str = None,
        workflow_name: str = None,
        shot_id: str = None
    ) -> Task:
        """创建旁白台词音频生成任务"""
        task = Task(
            type="narrator_audio",
            name=f"生成旁白音频: 镜{shot_index}",
            description=f"为章节 '{chapter_title}' 的分镜 {shot_index} 生成旁白音频: {text[:50]}{'...' if len(text) > 50 else ''}",
            novel_id=novel_id,
            chapter_id=chapter_id,
            shot_id=shot_id,
            character_id=character_id,
            status="pending",
            progress=0,
            current_step="等待处理",
            workflow_id=workflow_id,
            workflow_name=workflow_name
        )
        return self.create(task)

    def get_active_narrator_audio_task(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int
    ) -> Optional[Task]:
        """获取旁白台词音频进行中的任务"""
        return self.db.query(Task).filter(
            Task.novel_id == novel_id,
            Task.chapter_id == chapter_id,
            Task.type == "narrator_audio",
            Task.name.like(f"%镜{shot_index}%"),
            Task.status.in_(["pending", "running"])
        ).first()
