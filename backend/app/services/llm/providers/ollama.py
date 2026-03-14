"""
Ollama 提供商

支持 Ollama 本地模型服务。
"""
import httpx
import os
import re
import time
from typing import Dict, Any, Optional, List
from ..base import BaseLLMProvider, LLMConfig, LLMResponse, save_llm_log


class OllamaProvider(BaseLLMProvider):
    """
    Ollama 提供商

    支持 Ollama 本地模型服务。
    """

    PROVIDER_NAME = "ollama"

    def _get_endpoint(self) -> str:
        """获取 API 端点 URL"""
        base = self.config.api_url.rstrip("/")
        # Ollama 使用 OpenAI 兼容格式
        return f"{base}/chat/completions"

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {
            "Content-Type": "application/json"
        }
        # Ollama 可以不需要 API Key，但如果配置了也可以使用
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _get_proxy_config(self) -> Optional[str]:
        """Ollama 通常是本地服务，不需要代理"""
        return None

    def _build_request_body(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float,
        max_tokens: int,
        response_format: Optional[str]
    ) -> Dict[str, Any]:
        """构建请求体"""
        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": temperature,
            # Ollama 对 max_tokens 支持不稳定，不设置
        }
        return body

    def _parse_response(self, response_data: Dict[str, Any]) -> str:
        """解析响应"""
        # Ollama 返回格式与 OpenAI 兼容
        if "choices" in response_data and response_data["choices"]:
            message = response_data["choices"][0]["message"]
            content = message.get("content", "")
            # 处理 Ollama 某些模型可能返回空的 content 但有 reasoning
            if not content and "reasoning" in message:
                content = message["reasoning"]
            return content
        return response_data.get("content", "")

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

        # Ollama 不需要代理
        old_http_proxy = os.environ.pop('HTTP_PROXY', None)
        old_https_proxy = os.environ.pop('HTTPS_PROXY', None)
        old_http_proxy_lower = os.environ.pop('http_proxy', None)
        old_https_proxy_lower = os.environ.pop('https_proxy', None)

        transport = httpx.AsyncHTTPTransport(proxy=None)
        client = httpx.AsyncClient(transport=transport, timeout=300.0)
        used_proxy = False

        try:
            async with client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=300.0
                )

            # 恢复环境变量
            if old_http_proxy:
                os.environ['HTTP_PROXY'] = old_http_proxy
            if old_https_proxy:
                os.environ['HTTPS_PROXY'] = old_https_proxy
            if old_http_proxy_lower:
                os.environ['http_proxy'] = old_http_proxy_lower
            if old_https_proxy_lower:
                os.environ['https_proxy'] = old_https_proxy_lower

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
            print(f"[OllamaProvider] {error_msg}")
            traceback.print_exc()

            # 恢复环境变量
            if old_http_proxy:
                os.environ['HTTP_PROXY'] = old_http_proxy
            if old_https_proxy:
                os.environ['HTTPS_PROXY'] = old_https_proxy
            if old_http_proxy_lower:
                os.environ['http_proxy'] = old_http_proxy_lower
            if old_https_proxy_lower:
                os.environ['https_proxy'] = old_https_proxy_lower

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

    async def get_models(self) -> List[str]:
        """
        获取 Ollama 可用的模型列表

        Returns:
            模型名称列表
        """
        if not self.config.api_url:
            return []

        try:
            # 尝试 Ollama API
            ollama_url = re.sub(r'/v1/?$', '', self.config.api_url) + "/api/tags"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    ollama_url,
                    headers=self._get_headers()
                )

                if response.status_code == 200:
                    data = response.json()
                    return [m.get("name") or m.get("model") for m in data.get("models", [])]
        except Exception:
            pass
        return []
