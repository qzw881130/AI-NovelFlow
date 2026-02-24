"""
Ollama 提供商

支持 Ollama 本地模型服务。
"""
import httpx
import os
import re
from typing import Dict, Any, Optional, List
from ..base import BaseLLMProvider, LLMConfig, LLMResponse


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
        # Ollama 可以不需要 API Key
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
