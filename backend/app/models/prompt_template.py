from sqlalchemy import Column, String, DateTime, Text, Boolean, Enum as SQLEnum
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class PromptTemplate(Base):
    """提示词模板 - 支持人设生成和章节拆分"""
    __tablename__ = "prompt_templates"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)  # 提示词名称
    description = Column(Text, default="")  # 描述
    template = Column(Text, nullable=False)  # 提示词模板内容
    style = Column(Text, default="")  # 风格提示词（用于生成图片时添加风格描述）
    type = Column(String, default="character")  # 类型: character(人设), chapter_split(章节拆分)
    is_system = Column(Boolean, default=False)  # 是否系统预设（不可编辑）
    is_active = Column(Boolean, default=True)  # 是否启用
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
