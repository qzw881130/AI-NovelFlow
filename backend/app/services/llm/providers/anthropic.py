"""
Anthropic Claude 提供商

支持 Anthropic Claude API 格式。
"""
import httpx
from typing import Dict, Any, Optional
from ..base import BaseLLMProvider, LLMConfig, LLMResponse


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
        return response_data["content"][0]["text"]
