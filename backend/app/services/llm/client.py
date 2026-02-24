"""
LLM 统一客户端

提供统一的 LLM 调用接口，支持多厂商切换和 API Key 轮询。
"""
import httpx
import os
from typing import Optional, Dict, Any, Type
from .base import BaseLLMProvider, LLMConfig, LLMResponse
from .providers.openai import OpenAICompatibleProvider
from .providers.anthropic import AnthropicProvider
from .providers.gemini import GeminiProvider
from .providers.ollama import OllamaProvider


class LLMClient:
    """
    LLM 统一客户端
    
    提供统一的 LLM 调用接口， 支持多厂商切换和 API Key 轮询。
    """
    
    # 提供商映射
    _PROVIDERS = {
        "openai": OpenAICompatibleProvider,
        "deepseek": OpenAICompatibleProvider,  # DeepSeek 使用 OpenAI 兼容格式
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
        "ollama": OllamaProvider,
        "azure": OpenAICompatibleProvider,  # Azure 使用 OpenAI 兼容格式
        "aliyun-bailian": OpenAICompatibleProvider,  # 阿里云百炼使用 OpenAI 兼容格式
        "custom": OpenAICompatibleProvider,  # 自定义 API 使用 OpenAI 兼容格式
    }
    
    def __init__(self, config: LLMConfig):
        """
        初始化 LLM 客户端
        
        Args:
            config: LLM 配置
        """
        self.config = config
        self._provider = self._create_provider(config.provider)
        self._client: Optional[httpx.AsyncClient] = None
    
    def _create_provider(self, provider_name: str) -> Optional[BaseLLMProvider]:
        """
        创建提供商实例
        
        Args:
            provider_name: 提供商名称
            
        Returns:
            提供商实例
        """
        provider_class = self._PROVIDERS.get(provider_name)
        if not provider_class:
            raise ValueError(f"不支持的 LLM 提供商: {provider_name}")
        
        return provider_class(self.config)
    
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
            response_format: 响应格式
            
        Returns:
            LLMResponse 对象
        """
        return await self._provider.chat_completion(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format
        )
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None:
            proxy = self._provider._get_proxy_config()
            # 本地服务不需要代理
            if self.config.provider in ("ollama", "custom"):
                # 清除环境变量代理设置
                old_http = os.environ.pop("HTTP_PROXY", None)
                old_https = os.environ.pop("HTTPS_PROXY", None)
                transport = httpx.AsyncHTTPTransport(proxy=None)
                self._client = httpx.AsyncClient(transport=transport, timeout=300.0)
            else:
                self._client = httpx.AsyncClient(proxy=proxy, timeout=600.0)
        
        return self._client
    
    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None
