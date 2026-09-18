"""
Google Gemini 提供商

支持 Google Gemini API 格式。
"""
import httpx
import asyncio
import time
from typing import Dict, Any, Optional
from ..base import BaseLLMProvider, LLMConfig, LLMResponse, create_llm_log, update_llm_log, build_llm_request_info
from ..multimodal import canonical_log, native_content, redacted_wire, wire_evidence


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini 提供商

    支持 Google Gemini API 格式。
    """

    PROVIDER_NAME = "gemini"
    MULTIMODAL_WIRE = 'gemini-parts'

    def _get_endpoint(self) -> str:
        """获取 API 端点 URL"""
        base = self.config.api_url.rstrip("/")
        return f"{base}/models/{self.config.model}:generateContent"

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self._get_current_api_key(),
        }

    def _build_request_body(
        self,
        system_prompt: str,
        user_content: str | list[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[str]
    ) -> Dict[str, Any]:
        """构建请求体"""
        self.preflight_content(user_content)
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": native_content(user_content, self.MULTIMODAL_WIRE)}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }
        if response_format == "json_object":
            body["generationConfig"]["responseMimeType"] = "application/json"
        return body

    def _parse_response(self, response_data: Dict[str, Any]) -> str:
        """解析响应"""
        if not response_data.get("candidates"):
            return ""
        parts = response_data["candidates"][0]["content"]["parts"]
        if not isinstance(parts, list):
            raise TypeError("Gemini response parts must be a list")
        texts = []
        for part in parts:
            if not isinstance(part, dict):
                raise TypeError("Gemini response part must be an object")
            if part.get('thought') is True:
                continue
            if not isinstance(part.get('text'), str):
                raise TypeError("Gemini final response must contain text parts")
            texts.append(part['text'])
        return ''.join(texts)

    async def chat_completion(
        self,
        system_prompt: str,
        user_content: str | list[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        response_format: Optional[str] = None,
        task_type: str = None,
        prompt_template_name: str = None,
        novel_id: str = None,
        chapter_id: str = None,
        character_id: str = None
    ) -> LLMResponse:
        """
        发送对话请求

        Args:
            system_prompt: 系统提示词
            user_content: 用户内容
            temperature: 温度参数
            max_tokens: 最大 token 数
            response_format: 响应格式
            task_type: 任务类型
            novel_id: 小说 ID
            chapter_id: 章节 ID
            character_id: 角色 ID

        Returns:
            LLMResponse 对象
        """
        start_time = time.time()
        endpoint = self._get_endpoint()
        headers = self._get_headers()
        body = self._build_request_body(
            system_prompt, user_content, temperature, max_tokens, response_format
        )

        # 获取代理配置
        proxy = self._get_proxy_config()
        used_proxy = proxy is not None
        timeout = self.config.timeout or 300.0
        request_info = build_llm_request_info(
            provider=self.config.provider,
            base_url=self.config.api_url,
            endpoint=endpoint,
            model=self.config.model,
            headers=headers,
            payload=redacted_wire(body),
            proxy_url=proxy,
            timeout_seconds=timeout,
        )
        evidence = wire_evidence(self.config, user_content, body, self.MULTIMODAL_WIRE)
        if evidence:
            request_info['multimodal'] = evidence

        client = httpx.AsyncClient(proxy=proxy, timeout=timeout)

        log_id = None
        response = None
        try:
            async with client:
                log_id = create_llm_log(
                    provider=self.config.provider,
                    model=self.config.model,
                    system_prompt=system_prompt,
                    user_prompt=canonical_log(user_content),
                    prompt_template_name=prompt_template_name,
                    task_type=task_type,
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                    character_id=character_id,
                    used_proxy=used_proxy,
                    request_info=request_info,
                )
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=timeout
                )

            duration = time.time() - start_time

            if response.status_code == 200:
                data = response.json()
                return self._complete_response(log_id, data, duration)
            else:
                return self._http_error_response(log_id, response, duration)
        except asyncio.CancelledError:
            update_llm_log(log_id, status="error", error_message="请求被取消或超时，调用方已停止等待", duration=time.time() - start_time)
            raise
        except Exception as e:
            duration = time.time() - start_time
            return self._exception_response(log_id, e, duration, response=response)
