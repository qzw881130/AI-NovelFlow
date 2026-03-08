"""
API 依赖注入模块

集中管理所有 Repository 和 Service 的依赖注入函数，避免在各 API 文件中重复定义。
"""

from typing import Generator
from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories import (
    NovelRepository,
    ChapterRepository,
    CharacterRepository,
    SceneRepository,
    PropRepository,
    TaskRepository,
    WorkflowRepository,
    PromptTemplateRepository,
    ShotRepository,
)
from app.services.llm_service import LLMService
from app.services.comfyui import ComfyUIService


# ==================== Repository 依赖 ====================


def get_novel_repo(db: Session = Depends(get_db)) -> NovelRepository:
    """获取小说 Repository"""
    return NovelRepository(db)


def get_chapter_repo(db: Session = Depends(get_db)) -> ChapterRepository:
    """获取章节 Repository"""
    return ChapterRepository(db)


def get_character_repo(db: Session = Depends(get_db)) -> CharacterRepository:
    """获取角色 Repository"""
    return CharacterRepository(db)


def get_scene_repo(db: Session = Depends(get_db)) -> SceneRepository:
    """获取场景 Repository"""
    return SceneRepository(db)


def get_prop_repo(db: Session = Depends(get_db)) -> PropRepository:
    """获取道具 Repository"""
    return PropRepository(db)


def get_task_repo(db: Session = Depends(get_db)) -> TaskRepository:
    """获取任务 Repository"""
    return TaskRepository(db)


def get_workflow_repo(db: Session = Depends(get_db)) -> WorkflowRepository:
    """获取工作流 Repository"""
    return WorkflowRepository(db)


def get_prompt_template_repo(db: Session = Depends(get_db)) -> PromptTemplateRepository:
    """获取提示词模板 Repository"""
    return PromptTemplateRepository(db)


def get_shot_repo(db: Session = Depends(get_db)) -> ShotRepository:
    """获取分镜 Repository"""
    return ShotRepository(db)


# ==================== Service 依赖 ====================


def get_llm_service() -> LLMService:
    """获取 LLM 服务（每次调用创建新实例以获取最新配置）"""
    return LLMService()


def get_comfyui_service() -> ComfyUIService:
    """获取 ComfyUI 服务实例"""
    return ComfyUIService()
