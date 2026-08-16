"""
LLM 服务基类定义

定义所有 LLM 提供商必须实现的接口
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass
import json


def _sanitize_headers(headers: Dict[str, Any] = None) -> Dict[str, Any]:
    sanitized = dict(headers or {})
    for key in list(sanitized.keys()):
        if key.lower() in {"authorization", "x-api-key", "api-key", "apikey"}:
            sanitized[key] = "Bearer ***" if str(sanitized[key]).lower().startswith("bearer ") else "***"
    return sanitized


def build_llm_request_info(
    provider: str,
    base_url: str,
    endpoint: str,
    model: str,
    headers: Dict[str, Any],
    payload: Dict[str, Any],
    proxy_url: str = None,
    timeout_seconds: int | float = None,
) -> Dict[str, Any]:
    """构建用于日志展示的 LLM 请求参数，敏感字段会被脱敏。"""
    return {
        "provider": provider,
        "baseUrl": base_url,
        "url": endpoint,
        "model": model,
        "proxyUrl": proxy_url or "",
        "timeoutSeconds": timeout_seconds,
        "headers": _sanitize_headers(headers),
        "payload": payload,
    }


def save_llm_log(
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    response: str = None,
    status: str = "success",
    error_message: str = None,
    task_type: str = None,
    novel_id: str = None,
    chapter_id: str = None,
    character_id: str = None,
    used_proxy: bool = False,
    duration: float = None,
    request_info: Dict[str, Any] = None,
):
    """保存 LLM 调用日志到数据库（异步执行，不阻塞主流程）"""
    try:
        from app.core.database import SessionLocal
        from app.models.llm_log import LLMLog
        from app.constants import LOG_ERROR_MESSAGE_MAX_LENGTH

        db = SessionLocal()
        try:
            log = LLMLog(
                provider=provider,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
                status=status,
                error_message=error_message[:LOG_ERROR_MESSAGE_MAX_LENGTH] if error_message else None,
                task_type=task_type,
                novel_id=novel_id,
                chapter_id=chapter_id,
                character_id=character_id,
                used_proxy=used_proxy,
                duration=duration,
                request_info=json.dumps(request_info, ensure_ascii=False, indent=2) if request_info else None
            )
            db.add(log)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[LLM Log] 保存日志失败：{e}")


@dataclass
class LLMConfig:
    """LLM 配置数据类"""
    provider: str
    model: str
    api_url: str
    api_key: str
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None

    # 代理配置
    proxy_enabled: bool = False
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None


@dataclass
class LLMResponse:
    """LLM 响应数据类"""
    success: bool
    content: str = ""
    error: str = ""
    raw_response: Optional[Dict[str, Any]] = None
    duration: float = 0.0


class BaseLLMProvider(ABC):
    """
    LLM 提供商基类

    所有 LLM 提供商（OpenAI, Anthropic, Gemini 等）必须继承此类并实现抽象方法
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self._api_keys = []
        self._current_key_index = 0

        # 初始化 API Key 轮询
        if config.api_key:
            self._api_keys = [k.strip() for k in config.api_key.split(',') if k.strip()]

    @property
    def provider_name(self) -> str:
        """返回提供商名称"""
        return self.config.provider

    def _get_current_api_key(self) -> str:
        """获取当前 API Key，支持轮询"""
        if not self._api_keys:
            return self.config.api_key or ""

        current_key = self._api_keys[self._current_key_index]
        self._current_key_index = (self._current_key_index + 1) % len(self._api_keys)
        return current_key

    def _get_proxy_config(self) -> Optional[str]:
        """获取代理配置"""
        if not self.config.proxy_enabled:
            return None

        # 本地服务不需要代理
        if self.config.provider in ("ollama", "custom"):
            return None

        return self.config.https_proxy or self.config.http_proxy or None

    @abstractmethod
    async def chat_completion(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        response_format: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """
        发送对话请求

        Args:
            system_prompt: 系统提示词
            user_content: 用户内容
            temperature: 温度参数
            max_tokens: 最大 token 数
            response_format: 响应格式 (如 "json_object")

        Returns:
            LLMResponse 对象
        """
        pass

    @abstractmethod
    def _build_request_body(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float,
        max_tokens: int,
        response_format: Optional[str]
    ) -> Dict[str, Any]:
        """构建请求体"""
        pass

    @abstractmethod
    def _parse_response(self, response_data: Dict[str, Any]) -> str:
        """解析响应"""
        pass

    @abstractmethod
    def _get_endpoint(self) -> str:
        """获取 API 端点 URL"""
        pass

    @abstractmethod
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        pass
