"""LLM调用日志模型"""
from sqlalchemy import Column, String, Text, DateTime, Integer, JSON, Boolean, Float
from sqlalchemy.sql import func
from app.core.database import Base
import uuid


class LLMLog(Base):
    __tablename__ = "llm_logs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # 时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # LLM信息
    provider = Column(String, nullable=False)  # deepseek, openai, etc.
    model = Column(String, nullable=False)     # deepseek-chat, gpt-4o, etc.
    
    # 提示词
    system_prompt = Column(Text, nullable=True)
    user_prompt = Column(Text, nullable=False)
    
    # LLM响应
    response = Column(Text, nullable=True)
    
    # 状态
    status = Column(String, default="success")  # success, error
    error_message = Column(Text, nullable=True)
    
    # 任务类型
    task_type = Column(String, nullable=True)   # parse_characters, generate_character, split_chapter, etc.
    
    # 关联信息（可选）
    novel_id = Column(String, nullable=True)
    chapter_id = Column(String, nullable=True)
    character_id = Column(String, nullable=True)
    
    # 代理使用情况
    used_proxy = Column(Boolean, default=False)
    
    # 请求耗时（秒）
    duration = Column(Float, nullable=True)  # 请求耗时，单位秒
