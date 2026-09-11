"""
LLM 服务基类定义

定义所有 LLM 提供商必须实现的接口
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass
import httpx
import json
import uuid
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .metrics import normalize_metrics


def _sanitize_url(url):
    if not url:
        return url
    parts = urlsplit(url)
    netloc = parts.netloc.rsplit("@", 1)[-1]
    query = urlencode([
        (key, "***" if key.lower() in {"key", "api_key", "api-key", "token", "access_token"} else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ])
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def _sanitize_headers(headers: Dict[str, Any] = None) -> Dict[str, Any]:
    sanitized = dict(headers or {})
    for key in list(sanitized.keys()):
        if key.lower() in {"authorization", "x-api-key", "api-key", "apikey", "x-goog-api-key"}:
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
        "baseUrl": _sanitize_url(base_url),
        "url": _sanitize_url(endpoint),
        "model": model,
        "proxyUrl": _sanitize_url(proxy_url) or "",
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
    metrics: Dict[str, Any] = None,
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
            log.usage_metrics = metrics
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        print(f"[LLM Log] 更新日志失败：{e}")


def mark_matching_pending_llm_logs_error(
    task_type: str,
    novel_id: str = None,
    chapter_id: str = None,
    prompt_template_name: str = None,
    user_prompt: str = None,
    error_message: str = "LLM 调用已由调用方超时中断",
) -> int:
    """Mark pending logs for a timed-out call when cancellation did not reach provider cleanup."""
    try:
        from app.core.database import SessionLocal
        from app.models.llm_log import LLMLog
        from app.constants import LOG_ERROR_MESSAGE_MAX_LENGTH

        db = SessionLocal()
        try:
            query = db.query(LLMLog).filter(LLMLog.status == "pending")
            if task_type:
                query = query.filter(LLMLog.task_type == task_type)
            if novel_id:
                query = query.filter(LLMLog.novel_id == novel_id)
            if chapter_id:
                query = query.filter(LLMLog.chapter_id == chapter_id)
            if prompt_template_name:
                query = query.filter(LLMLog.prompt_template_name == prompt_template_name)
            if user_prompt:
                query = query.filter(LLMLog.user_prompt == user_prompt)

            logs = query.all()
            for log in logs:
                log.status = "error"
                log.error_message = error_message[:LOG_ERROR_MESSAGE_MAX_LENGTH]
            if logs:
                db.commit()
            return len(logs)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        print(f"[LLM Log] 标记超时日志失败：{e}")
        return 0


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
    failure_kind: Optional[str] = None
    diagnostic_content: Any = None  # Candidate or undecodable response body, never prompt content.
    diagnostic_type: Optional[str] = None


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

    def _complete_response(self, log_id, data, duration):
        metrics = normalize_metrics(self.config.provider, data, duration)
        content = ""
        error = ""
        candidate = None
        diagnostic_type = None
        try:
            candidate = self._parse_response(data)
            if metrics["finish_reason"] in {"length", "max_tokens", "MAX_TOKENS"}:
                error = "API 响应因长度限制被截断，请提高最大 token 数或缩短输入后重试"
            elif not isinstance(candidate, str):
                error = "API 返回成功状态，但响应内容不是字符串"
            elif not candidate.strip():
                error = "API 返回成功状态，但响应内容为空"
            else:
                content = candidate
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
            error = "API 响应格式无效"
            diagnostic_type = type(exc).__name__
        if error and diagnostic_type is None:
            diagnostic_type = type(candidate).__name__

        log_content = candidate
        if log_content is not None and not isinstance(log_content, str):
            try:
                log_content = json.dumps(log_content, ensure_ascii=False)
            except (TypeError, ValueError):
                log_content = None
        update_llm_log(
            log_id, status="error" if error else "success", response=log_content,
            error_message=error or None, duration=duration, metrics=metrics,
        )
        return LLMResponse(
            success=not error, content=content, error=error,
            raw_response=data, duration=duration,
            failure_kind="INVALID_OUTPUT" if error else None,
            diagnostic_content=candidate if error else None,
            diagnostic_type=diagnostic_type,
        )

    def _http_error_response(self, log_id, response, duration):
        metrics = None
        try:
            metrics = normalize_metrics(self.config.provider, response.json(), duration)
        except ValueError:
            pass
        error = f"API 错误 ({response.status_code}): {response.text}"
        update_llm_log(log_id, status="error", error_message=error, duration=duration, metrics=metrics)
        return LLMResponse(success=False, error=error, duration=duration, failure_kind="SERVICE_ERROR")

    def _exception_response(self, log_id, exc, duration, response=None):
        diagnostic_content = None
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            failure_kind = "TIMEOUT"
        elif isinstance(exc, (httpx.HTTPError, ConnectionError)):
            failure_kind = "SERVICE_ERROR"
        elif (response is not None and response.status_code == 200
              and isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError))):
            failure_kind = "INVALID_OUTPUT"
            diagnostic_content = response.text
        else:
            failure_kind = "UNKNOWN_ERROR"

        error = f"请求异常：[{type(exc).__name__}] {str(exc) or '(无详细错误信息)'}"
        # Keep only body text, not request/response objects, and redact reflected API keys.
        for api_key in self._api_keys:
            error = error.replace(api_key, "***")
            if diagnostic_content is not None:
                diagnostic_content = diagnostic_content.replace(api_key, "***")
        print(f"[{type(self).__name__}] {error}")
        update_llm_log(
            log_id, status="error", response=diagnostic_content,
            error_message=error, duration=duration,
        )
        return LLMResponse(
            success=False, error=error, duration=duration, failure_kind=failure_kind,
            diagnostic_content=diagnostic_content,
            diagnostic_type="str" if diagnostic_content is not None else None,
        )

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
        user_content: str | list[Dict[str, Any]],
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
        user_content: str | list[Dict[str, Any]],
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
