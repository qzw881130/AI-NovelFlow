"""应用配置 - 支持从环境变量和数据库加载"""
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    # App
    APP_NAME: str = "NovelFlow"
    DEBUG: bool = True
    
    # Database
    DATABASE_URL: str = "sqlite:///./novelflow.db"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # LLM Configuration (多厂商支持) - 默认值，会被数据库配置覆盖
    LLM_PROVIDER: str = "deepseek"
    LLM_MODEL: str = "deepseek-chat"
    LLM_API_URL: str = "https://api.deepseek.com"
    LLM_API_KEY: str = ""
    LLM_MAX_TOKENS: Optional[int] = None  # 最大token数
    LLM_TEMPERATURE: Optional[str] = None  # 温度参数
    
    # Proxy Configuration (代理配置)
    PROXY_ENABLED: bool = False
    HTTP_PROXY: Optional[str] = None
    HTTPS_PROXY: Optional[str] = None
    
    # Legacy DeepSeek config (兼容旧配置)
    DEEPSEEK_API_URL: str = "https://api.deepseek.com"
    DEEPSEEK_API_KEY: str = ""
    
    # ComfyUI
    COMFYUI_HOST: str = "http://192.168.50.1:8288"
    
    # Output
    OUTPUT_DIR: str = "./output"
    
    # AI解析角色系统提示词
    PARSE_CHARACTERS_PROMPT: Optional[str] = None
    
    class Config:
        env_file = ".env"
        validate_assignment = True  # 允许运行时修改属性
        extra = "ignore"  # 忽略额外字段


# 全局设置实例（用于运行时修改）
_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    """获取应用配置
    
    优先从内存中的实例获取，如果不存在则创建新实例。
    数据库配置会在应用启动时加载到该实例中。
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def reload_settings_from_db(db_config: dict) -> None:
    """从数据库配置重新加载设置
    
    在应用启动时调用，将数据库中的配置加载到内存中。
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    
    # 更新配置
    if db_config.get("llm_provider"):
        _settings_instance.LLM_PROVIDER = db_config["llm_provider"]
    if db_config.get("llm_model"):
        _settings_instance.LLM_MODEL = db_config["llm_model"]
    if db_config.get("llm_api_url"):
        _settings_instance.LLM_API_URL = db_config["llm_api_url"]
        _settings_instance.DEEPSEEK_API_URL = db_config["llm_api_url"]
    if db_config.get("llm_api_key"):
        _settings_instance.LLM_API_KEY = db_config["llm_api_key"]
        _settings_instance.DEEPSEEK_API_KEY = db_config["llm_api_key"]
    if "llm_max_tokens" in db_config:
        _settings_instance.LLM_MAX_TOKENS = db_config["llm_max_tokens"]
    if "llm_temperature" in db_config:
        _settings_instance.LLM_TEMPERATURE = db_config["llm_temperature"]
    
    if db_config.get("proxy_enabled") is not None:
        _settings_instance.PROXY_ENABLED = db_config["proxy_enabled"]
    if db_config.get("http_proxy"):
        _settings_instance.HTTP_PROXY = db_config["http_proxy"]
    if db_config.get("https_proxy"):
        _settings_instance.HTTPS_PROXY = db_config["https_proxy"]
    
    if db_config.get("comfyui_host"):
        _settings_instance.COMFYUI_HOST = db_config["comfyui_host"]
    
    if db_config.get("parse_characters_prompt"):
        _settings_instance.PARSE_CHARACTERS_PROMPT = db_config["parse_characters_prompt"]


def update_settings(updates: dict) -> None:
    """更新内存中的设置"""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    
    for key, value in updates.items():
        if hasattr(_settings_instance, key.upper()):
            setattr(_settings_instance, key.upper(), value)
