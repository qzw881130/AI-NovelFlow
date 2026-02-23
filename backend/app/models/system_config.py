"""系统配置模型 - 持久化存储 LLM、代理等配置"""
from sqlalchemy import Column, String, Text, Boolean, DateTime, Integer
from sqlalchemy.sql import func

from app.core.database import Base


class SystemConfig(Base):
    __tablename__ = "system_configs"
    
    # 使用单例模式，只有一条记录
    id = Column(String, primary_key=True, default="default")
    
    # LLM 配置
    llm_provider = Column(String, default="deepseek")
    llm_model = Column(String, default="deepseek-chat")
    llm_api_url = Column(String, default="https://api.deepseek.com")
    llm_api_key = Column(Text, nullable=True)  # 加密存储
    llm_max_tokens = Column(Integer, nullable=True)  # 最大token数
    llm_temperature = Column(String, nullable=True)  # 温度参数（字符串类型，支持范围0.0-2.0）
    
    # 代理配置
    proxy_enabled = Column(Boolean, default=False)
    http_proxy = Column(String, nullable=True)
    https_proxy = Column(String, nullable=True)
    
    # ComfyUI 配置
    comfyui_host = Column(String, default="http://192.168.50.1:8288")
    
    # 输出配置
    output_resolution = Column(String, default="1920x1080")
    output_frame_rate = Column(Integer, default=24)
    
    # AI解析角色系统提示词
    parse_characters_prompt = Column(Text, nullable=True)
    
    # 界面配置
    language = Column(String, default="zh-CN")  # 语言设置
    timezone = Column(String, default="Asia/Shanghai")  # 时区设置
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
