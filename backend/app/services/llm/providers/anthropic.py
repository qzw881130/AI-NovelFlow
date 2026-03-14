"""
Anthropic Claude 提供商

支持 Anthropic Claude API 格式。
"""
import httpx
import time
from typing import Dict, Any, Optional
from ..base import BaseLLMProvider, LLMConfig, LLMResponse, save_llm_log


class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic Claude 提供商

    支持 Anthropic Claude API 格式。
    """

    PROVIDER_NAME = "anthropic"

    def _get_endpoint(self) -> str:
        """获取 API 端点 URL"""
        base = self.config.api_url.rstrip("/")
        return f"{base}/messages"

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "x-api-key": self._get_current_api_key(),
            "anthropic-version": "2023-06-01"
        }

    def _build_request_body(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float,
        max_tokens: int,
        response_format: Optional[str]
    ) -> Dict[str, Any]:
        """构建请求体"""
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

    def _parse_response(self, response_data: Dict[str, Any]) -> str:
        """解析响应"""
        if "content" in response_data and response_data["content"]:
            return response_data["content"][0]["text"]
        return ""

    async def chat_completion(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        response_format: Optional[str] = None,
        task_type: str = None,
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

        client = httpx.AsyncClient(proxy=proxy, timeout=600.0)

        try:
            async with client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=300.0
                )

            duration = time.time() - start_time

            if response.status_code == 200:
                data = response.json()
                content = self._parse_response(data)

                save_llm_log(
                    provider=self.config.provider,
                    model=self.config.model,
                    system_prompt=system_prompt,
                    user_prompt=user_content,
                    response=content,
                    status="success",
                    task_type=task_type,
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                    character_id=character_id,
                    used_proxy=used_proxy,
                    duration=duration
                )

                return LLMResponse(
                    success=True,
                    content=content,
                    raw_response=data,
                    duration=duration
                )
            else:
                error_msg = f"API 错误 ({response.status_code}): {response.text}"
                save_llm_log(
                    provider=self.config.provider,
                    model=self.config.model,
                    system_prompt=system_prompt,
                    user_prompt=user_content,
                    status="error",
                    error_message=error_msg,
                    task_type=task_type,
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                    character_id=character_id,
                    used_proxy=used_proxy,
                    duration=duration
                )

                return LLMResponse(
                    success=False,
                    error=error_msg,
                    duration=duration
                )
        except Exception as e:
            import traceback
            error_type = type(e).__name__
            error_detail = str(e) if str(e) else "(无详细错误信息)"
            error_msg = f"请求异常：[{error_type}] {error_detail}"
            print(f"[AnthropicProvider] {error_msg}")
            traceback.print_exc()

            duration = time.time() - start_time
            save_llm_log(
                provider=self.config.provider,
                model=self.config.model,
                system_prompt=system_prompt,
                user_prompt=user_content,
                status="error",
                error_message=error_msg,
                task_type=task_type,
                novel_id=novel_id,
                chapter_id=chapter_id,
                character_id=character_id,
                used_proxy=used_proxy,
                duration=duration
            )

            return LLMResponse(
                success=False,
                error=error_msg,
                duration=duration
            )
