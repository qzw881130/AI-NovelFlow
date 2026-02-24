"""LLM调用日志API"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.core.database import get_db
from app.models.llm_log import LLMLog
from app.repositories import LLMLogRepository

router = APIRouter()

# 上海时区 (东八区)
SHANGHAI_TZ = timezone(timedelta(hours=8))
UTC_TZ = timezone.utc


def get_llmlog_repo(db: Session = Depends(get_db)) -> LLMLogRepository:
    """获取 LLMLogRepository 实例"""
    return LLMLogRepository(db)

def to_shanghai_time(dt: datetime) -> str:
    """将时间转换为上海时间字符串
    
    处理各种时区情况：
    - SQLite 的 func.now() 返回的是 UTC 时间（无时区）
    - 如果时间是 naive（无时区），假设为 UTC 时间，然后转为上海时间
    - 如果时间是 aware（有时区），直接转为上海时间
    """
    if not dt:
        return None
    
    if dt.tzinfo is None:
        # Naive 时间，先添加 UTC 时区，然后转为上海时间
        dt = dt.replace(tzinfo=UTC_TZ)
    
    return dt.astimezone(SHANGHAI_TZ).isoformat()


@router.get("/")
async def get_llm_logs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    provider: Optional[str] = Query(None, description="LLM厂商筛选"),
    model: Optional[str] = Query(None, description="模型筛选"),
    task_type: Optional[str] = Query(None, description="任务类型筛选"),
    status: Optional[str] = Query(None, description="状态筛选: success/error"),
    novel_id: Optional[str] = Query(None, description="小说ID筛选"),
    llmlog_repo: LLMLogRepository = Depends(get_llmlog_repo)
):
    """获取LLM调用日志列表"""
    logs, total = llmlog_repo.list_paginated(
        page=page,
        page_size=page_size,
        provider=provider,
        model=model,
        task_type=task_type,
        status=status,
        novel_id=novel_id
    )
    
    return {
        "success": True,
        "data": {
            "items": [
                {
                    "id": log.id,
                    "created_at": to_shanghai_time(log.created_at),
                    "provider": log.provider,
                    "model": log.model,
                    "system_prompt": log.system_prompt,
                    "user_prompt": log.user_prompt,
                    "response": log.response,
                    "status": log.status,
                    "error_message": log.error_message,
                    "task_type": log.task_type,
                    "novel_id": log.novel_id,
                    "chapter_id": log.chapter_id,
                    "character_id": log.character_id,
                    "used_proxy": log.used_proxy,
                    "duration": log.duration  # 添加耗时字段
                }
                for log in logs
            ],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size
            }
        }
    }


@router.get("/filters")
async def get_log_filters(llmlog_repo: LLMLogRepository = Depends(get_llmlog_repo)):
    """获取日志筛选选项"""
    providers = llmlog_repo.get_distinct_providers()
    models = llmlog_repo.get_distinct_models()
    task_types = llmlog_repo.get_distinct_task_types()
    
    return {
        "success": True,
        "data": {
            "providers": providers,
            "models": models,
            "task_types": task_types
        }
    }


@router.get("/{log_id}")
async def get_llm_log_detail(
    log_id: str, 
    llmlog_repo: LLMLogRepository = Depends(get_llmlog_repo)
):
    """获取单个日志详情"""
    log = llmlog_repo.get_by_id(log_id)
    
    if not log:
        return {"success": False, "message": "日志不存在"}
    
    return {
        "success": True,
        "data": {
            "id": log.id,
            "created_at": to_shanghai_time(log.created_at),
            "provider": log.provider,
            "model": log.model,
            "system_prompt": log.system_prompt,
            "user_prompt": log.user_prompt,
            "response": log.response,
            "status": log.status,
            "error_message": log.error_message,
            "task_type": log.task_type,
            "novel_id": log.novel_id,
            "chapter_id": log.chapter_id,
            "character_id": log.character_id,
            "used_proxy": log.used_proxy,
            "duration": log.duration  # 添加耗时字段
        }
    }
