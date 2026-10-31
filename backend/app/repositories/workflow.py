"""
Workflow Repository 层

封装工作流相关的数据库查询逻辑
"""
import os
from typing import List, Optional

from sqlalchemy.orm import Session

from app.constants.workflow import RETIRED_LTX2_TRANSITION_WORKFLOW_FILES
from app.models.workflow import Workflow


class WorkflowRepository:
    """工作流数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def is_available_for_generation(workflow: Workflow) -> bool:
        return not (
            workflow.is_system and workflow.type == "transition" and workflow.file_path
            and os.path.basename(workflow.file_path) in RETIRED_LTX2_TRANSITION_WORKFLOW_FILES
        )
    
    def list_all(self) -> List[Workflow]:
        """获取所有工作流（系统优先，按创建时间倒序）"""
        workflows = self.db.query(Workflow).order_by(
            Workflow.is_system.desc(),
            Workflow.created_at.desc()
        ).all()
        return [workflow for workflow in workflows if self.is_available_for_generation(workflow)]
    
    def list_by_type(self, workflow_type: str) -> List[Workflow]:
        """按类型获取工作流列表"""
        workflows = self.db.query(Workflow).filter(
            Workflow.type == workflow_type
        ).order_by(
            Workflow.is_system.desc(),
            Workflow.created_at.desc()
        ).all()
        return [workflow for workflow in workflows if self.is_available_for_generation(workflow)]
    
    def get_by_id(self, workflow_id: str) -> Optional[Workflow]:
        """根据 ID 获取工作流"""
        return self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
    
    def get_by_file_path(self, file_path: str, is_system: bool = True) -> Optional[Workflow]:
        """根据文件路径获取工作流"""
        return self.db.query(Workflow).filter(
            Workflow.file_path == file_path,
            Workflow.is_system == is_system
        ).first()
    
    def get_active_by_type(self, workflow_type: str) -> Optional[Workflow]:
        """获取指定类型的激活工作流"""
        workflows = self.db.query(Workflow).filter(
            Workflow.type == workflow_type,
            Workflow.is_active == True
        ).all()
        return next((workflow for workflow in workflows if self.is_available_for_generation(workflow)), None)
    
    def get_first_system_by_type(self, workflow_type: str) -> Optional[Workflow]:
        """获取指定类型的第一个系统工作流"""
        workflows = self.db.query(Workflow).filter(
            Workflow.type == workflow_type,
            Workflow.is_system == True
        ).order_by(Workflow.created_at.asc()).all()
        return next((workflow for workflow in workflows if self.is_available_for_generation(workflow)), None)
    
    def list_active_by_type(self, workflow_type: str) -> List[Workflow]:
        """获取指定类型的所有激活工作流"""
        workflows = self.db.query(Workflow).filter(
            Workflow.type == workflow_type,
            Workflow.is_active == True
        ).order_by(Workflow.created_at.asc()).all()
        return [workflow for workflow in workflows if self.is_available_for_generation(workflow)]
    
    def deactivate_all_by_type(self, workflow_type: str) -> int:
        """将指定类型的所有工作流设为非激活"""
        count = self.db.query(Workflow).filter(
            Workflow.type == workflow_type
        ).update({"is_active": False})
        self.db.commit()
        return count
    
    def create(self, workflow: Workflow) -> Workflow:
        """创建工作流"""
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow
    
    def update(self, workflow: Workflow) -> Workflow:
        """更新工作流"""
        self.db.commit()
        self.db.refresh(workflow)
        return workflow
    
    def delete(self, workflow: Workflow) -> None:
        """删除工作流"""
        self.db.delete(workflow)
        self.db.commit()
    
    def exists_by_path(self, file_path: str, is_system: bool = True) -> bool:
        """检查工作流是否存在"""
        return self.db.query(Workflow).filter(
            Workflow.file_path == file_path,
            Workflow.is_system == is_system
        ).first() is not None
