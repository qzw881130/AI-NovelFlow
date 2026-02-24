"""
LLMLog Repository 层

封装LLM调用日志相关的数据库查询逻辑
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.llm_log import LLMLog


class LLMLogRepository:
    """LLM调用日志数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_all(self, limit: int = 50) -> List[LLMLog]:
        """获取所有日志（按创建时间倒序）"""
        return self.db.query(LLMLog).order_by(desc(LLMLog.created_at)).limit(limit).all()
    
    def list_paginated(
        self, 
        page: int = 1, 
        page_size: int = 20,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        status: Optional[str] = None,
        novel_id: Optional[str] = None
    ) -> tuple[List[LLMLog], int]:
        """分页获取日志（支持筛选）"""
        query = self.db.query(LLMLog)
        
        # 应用筛选条件
        if provider:
            query = query.filter(LLMLog.provider == provider)
        if model:
            query = query.filter(LLMLog.model == model)
        if task_type:
            query = query.filter(LLMLog.task_type == task_type)
        if status:
            query = query.filter(LLMLog.status == status)
        if novel_id:
            query = query.filter(LLMLog.novel_id == novel_id)
        
        # 获取总数
        total = query.count()
        
        # 分页
        logs = query.order_by(desc(LLMLog.created_at)).offset((page - 1) * page_size).limit(page_size).all()
        
        return logs, total
    
    def get_by_id(self, log_id: str) -> Optional[LLMLog]:
        """根据 ID 获取日志"""
        return self.db.query(LLMLog).filter(LLMLog.id == log_id).first()
    
    def get_distinct_providers(self) -> List[str]:
        """获取所有不重复的 provider"""
        results = self.db.query(LLMLog.provider).distinct().all()
        return [r[0] for r in results if r[0]]
    
    def get_distinct_models(self) -> List[str]:
        """获取所有不重复的 model"""
        results = self.db.query(LLMLog.model).distinct().all()
        return [r[0] for r in results if r[0]]
    
    def get_distinct_task_types(self) -> List[str]:
        """获取所有不重复的 task_type"""
        results = self.db.query(LLMLog.task_type).distinct().all()
        return [r[0] for r in results if r[0]]
    
    def create(self, log: LLMLog) -> LLMLog:
        """创建日志"""
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log
    
    def delete(self, log: LLMLog) -> None:
        """删除日志"""
        self.db.delete(log)
        self.db.commit()
