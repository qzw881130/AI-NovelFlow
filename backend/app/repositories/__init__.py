"""
Repository 层

封装数据库查询逻辑，避免 N+1 查询问题
"""

from .novel_repository import NovelRepository
from .chapter_repository import ChapterRepository
from .character_repository import CharacterRepository
from .scene_repository import SceneRepository
from .prop_repository import PropRepository
from .task import TaskRepository
from .workflow import WorkflowRepository
from .prompt_template import PromptTemplateRepository
from .test_case import TestCaseRepository
from .llm_log import LLMLogRepository
from .shot_repository import ShotRepository
from .audio_drive import AudioDriveRepository

__all__ = [
    "NovelRepository",
    "ChapterRepository",
    "CharacterRepository",
    "SceneRepository",
    "PropRepository",
    "TaskRepository",
    "WorkflowRepository",
    "PromptTemplateRepository",
    "TestCaseRepository",
    "LLMLogRepository",
    "ShotRepository",
    "AudioDriveRepository",
]
