"""
OpenAI 兼容的 LLM 提供商

支持 OpenAI、 DeepSeek、 Azure 等使用 OpenAI 典格格式的 LLM 服务。
"""
import httpx
from typing import Dict, Any, Optional
from ..base import BaseLLMProvider, LLMConfig, LLMResponse


class OpenAICompatibleProvider(BaseLLMProvider):
    """
    OpenAI 兼容的 LLM 提供商
    
    支持 OpenAI、 DeepSeek、 Azure 等使用 OpenAI 兎格式 API 的服务。
    """
    
    PROVIDER_NAME = "openai_compatible"
    
    def _get_endpoint(self) -> str:
        """获取 API 端点 URL"""
        base = self.config.api_url.rstrip("/")
        return f"{base}/chat/completions"
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_current_api_key()}"
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
            "max_tokens": max_tokens,
            **({"type": "json_object"} if response_format == "json_object" else {})
        }
    
    def _parse_response(self, response_data: Dict[str, Any]) -> str:
        """解析响应"""
        if "choices" in response_data and response_data["choices"]:
            return response_data["choices"][0]["message"]["content"]
        return response_data.get("content", "")
