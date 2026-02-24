"""
LLM 服务基类定义

定义所有 LLM 提供商必须实现的接口
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class LLMConfig:
    """LLM 配置数据类"""
    provider: str
    model: str
    api_url: str
    api_key: str
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    
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
        response_format: Optional[str] = None
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
    def build_request_body(
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
    def parse_response(self, response_data: Dict[str, Any]) -> str:
        """解析响应"""
        pass
    
    @abstractmethod
    def get_endpoint(self) -> str:
        """获取 API 端点 URL"""
        pass
    
    @abstractmethod
    def get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        pass
