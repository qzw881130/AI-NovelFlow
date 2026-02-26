from sqlalchemy import Column, String, DateTime, Text, Boolean, Enum as SQLEnum
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class PromptTemplate(Base):
    """提示词模板 - 支持多种类型的提示词管理
    
    类型包括：
    - style: 风格提示词（用于图片生成的风格描述）
    - character_parse: 角色解析提示词（从小说文本解析角色信息）
    - scene_parse: 场景解析提示词（从小说文本解析场景信息）
    - character: 角色生成提示词（生成角色图片）
    - scene: 场景生成提示词（生成场景图片）
    - chapter_split: 分镜拆分提示词（将章节拆分为分镜）
    """
    __tablename__ = "prompt_templates"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)  # 提示词名称
    description = Column(Text, default="")  # 描述
    template = Column(Text, nullable=False)  # 提示词模板内容
    type = Column(String, default="character")  # 类型: style, character_parse, scene_parse, character, scene, chapter_split
    is_system = Column(Boolean, default=False)  # 是否系统预设（不可编辑）
    is_active = Column(Boolean, default=True)  # 是否启用
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
