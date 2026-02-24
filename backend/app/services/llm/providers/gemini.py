"""
Google Gemini 提供商

支持 Google Gemini API 格式。
"""
import httpx
from typing import Dict, Any, Optional
from ..base import BaseLLMProvider, LLMConfig, LLMResponse


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini 提供商
    
    支持 Google Gemini API 格式。
    """
    
    PROVIDER_NAME = "gemini"
    
    def _get_endpoint(self) -> str:
        """获取 API 端点 URL"""
        base = self.config.api_url.rstrip("/")
        return f"{base}/models/{self.config.model}:generateContent?key={self._get_current_api_key()}"
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
                "Content-Type": "application/json"
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
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": system_prompt + "\n\n" + user_content}]}
            ],
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
        return response_data["candidates"][0]["content"]["parts"][0]["text"]
