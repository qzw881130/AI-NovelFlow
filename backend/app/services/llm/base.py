"""
LLM 服务基类定义

定义所有 LLM 提供商必须实现的接口
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass
import json
import uuid


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


def create_llm_log(
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    prompt_template_name: str = None,
    task_type: str = None,
    novel_id: str = None,
    chapter_id: str = None,
    character_id: str = None,
    used_proxy: bool = False,
    request_info: Dict[str, Any] = None,
) -> Optional[str]:
    """在请求发出前创建一条进行中的 LLM 调用日志。"""
    log_id = str(uuid.uuid4())
    try:
        from app.core.database import SessionLocal
        from app.models.llm_log import LLMLog

        db = SessionLocal()
        try:
            log = LLMLog(
                id=log_id,
                provider=provider,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                prompt_template_name=prompt_template_name,
                status="pending",
                task_type=task_type,
                novel_id=novel_id,
                chapter_id=chapter_id,
                character_id=character_id,
                used_proxy=used_proxy,
                request_info=json.dumps(request_info, ensure_ascii=False, indent=2, default=str) if request_info else None,
            )
            db.add(log)
            db.commit()
            return log_id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        print(f"[LLM Log] 创建日志失败：{e}")
        return None


def update_llm_log(
    log_id: Optional[str],
    status: str,
    response: str = None,
    error_message: str = None,
    duration: float = None,
) -> None:
    """请求结束后更新同一条 LLM 调用日志。"""
    if not log_id:
        return

    try:
        from app.core.database import SessionLocal
        from app.models.llm_log import LLMLog
        from app.constants import LOG_ERROR_MESSAGE_MAX_LENGTH

        db = SessionLocal()
        try:
            log = db.query(LLMLog).filter(LLMLog.id == log_id).first()
            if not log:
                raise RuntimeError(f"日志不存在: {log_id}")
            if log.status == "error" and log.error_message == "任务被用户取消，LLM 响应已忽略":
                return
            log.response = response
            log.status = status
            log.error_message = error_message[:LOG_ERROR_MESSAGE_MAX_LENGTH] if error_message else None
            log.duration = duration
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        print(f"[LLM Log] 更新日志失败：{e}")


@dataclass
class LLMConfig:
    """LLM 配置数据类"""
    provider: str
    model: str
    api_url: str
    api_key: str
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    timeout: Optional[int] = None  # 请求超时（秒）

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
