"""
LLM 服务工厂

提供便捷的 LLM 服务创建和管理方法。
"""
import time
from typing import Optional, Dict, Any
from app.core.config import get_settings
from .base import LLMConfig, LLMResponse
from .client import LLMClient


# 全局客户端实例缓存（用于日志记录等元数据）
_client_instance: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """
    获取 LLM 客户端实例
    
    每次调用创建新实例以获取最新配置。
    
    Returns:
        LLMClient 实例
    """
    global _client_instance
    
    settings = get_settings()
    
    config = LLMConfig(
        provider=settings.LLM_PROVIDER,
        model=settings.LLM_MODEL,
        api_url=settings.LLM_API_URL,
        api_key=settings.LLM_API_KEY,
        max_tokens=settings.LLM_MAX_TOKENS,
        temperature=float(settings.LLM_TEMPERATURE) if settings.LLM_TEMPERATURE else None,
        proxy_enabled=settings.PROXY_ENABLED,
        http_proxy=settings.HTTP_PROXY,
        https_proxy=settings.HTTPS_PROXY,
    )
    
    _client_instance = LLMClient(config)
    
    return _client_instance


def get_llm_config() -> LLMConfig:
    """
    获取当前 LLM 配置
    
    Returns:
        LLMConfig 对象
    """
    settings = get_settings()
    
    return LLMConfig(
        provider=settings.LLM_PROVIDER,
        model=settings.LLM_MODEL,
        api_url=settings.LLM_API_URL,
        api_key=settings.LLM_API_KEY,
        max_tokens=settings.LLM_MAX_TOKENS,
        temperature=float(settings.LLM_TEMPERATURE) if settings.LLM_TEMPERATURE else None,
        proxy_enabled=settings.PROXY_ENABLED,
        http_proxy=settings.HTTP_PROXY,
        https_proxy=settings.HTTPS_PROXY,
    )


async def llm_chat(
    system_prompt: str,
    user_content: str,
    temperature: float = 0.7,
    max_tokens: int = 4000,
    response_format: Optional[str] = None,
    **kwargs
) -> LLMResponse:
    """
    便捷的 LLM 对话函数
    
    Args:
        system_prompt: 系统提示词
        user_content: 用户内容
        temperature: 温度参数
        max_tokens: 最大 token 数
        response_format: 响应格式
        
    Returns:
        LLMResponse 对象
    """
    client = get_llm_client()
    return await client.chat_completion(
        system_prompt=system_prompt,
        user_content=user_content,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
    )


# 别名，保持向后兼容
get_llm_service = get_llm_client


__all__ = [
    "LLMConfig",
    "LLMResponse", 
    "LLMClient",
    "get_llm_client",
    "get_llm_config",
    "get_llm_service",
    "llm_chat",
]
