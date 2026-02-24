"""
Workflow Repository 层

封装工作流相关的数据库查询逻辑
"""
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.workflow import Workflow


class WorkflowRepository:
    """工作流数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_all(self) -> List[Workflow]:
        """获取所有工作流（系统优先，按创建时间倒序）"""
        return self.db.query(Workflow).order_by(
            Workflow.is_system.desc(),
            Workflow.created_at.desc()
        ).all()
    
    def list_by_type(self, workflow_type: str) -> List[Workflow]:
        """按类型获取工作流列表"""
        return self.db.query(Workflow).filter(
            Workflow.type == workflow_type
        ).order_by(
            Workflow.is_system.desc(),
            Workflow.created_at.desc()
        ).all()
    
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
        return self.db.query(Workflow).filter(
            Workflow.type == workflow_type,
            Workflow.is_active == True
        ).first()
    
    def get_first_system_by_type(self, workflow_type: str) -> Optional[Workflow]:
        """获取指定类型的第一个系统工作流"""
        return self.db.query(Workflow).filter(
            Workflow.type == workflow_type,
            Workflow.is_system == True
        ).order_by(Workflow.created_at.asc()).first()
    
    def list_active_by_type(self, workflow_type: str) -> List[Workflow]:
        """获取指定类型的所有激活工作流"""
        return self.db.query(Workflow).filter(
            Workflow.type == workflow_type,
            Workflow.is_active == True
        ).order_by(Workflow.created_at.asc()).all()
    
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
