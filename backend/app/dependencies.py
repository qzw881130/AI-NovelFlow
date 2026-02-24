"""
依赖注入管理

提供统一的服务实例管理。
"""
from functools import lru_cache
from typing import Optional

from app.services.llm_service import LLMService
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage


# LLM 服务实例缓存
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """
    获取 LLMService 实例（带缓存)
    """
    global _llm_service
    
    if _llm_service is None:
        _llm_service = LLMService()
    
    return _llm_service


# ComfyUI 服务实例缓存
_comfyui_service: Optional[ComfyUIService] = None


def get_comfyui_service() -> ComfyUIService:
    """获取 ComfyUI 服务实例"""
    if _comfyui_service is None:
        _comfyui_service = ComfyUIService()
    
    return _comfyui_service


def get_file_storage():
    """获取文件存储实例"""
    return file_storage
