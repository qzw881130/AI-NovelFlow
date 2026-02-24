from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Scene(Base):
    """场景模型 - 场景库管理"""
    __tablename__ = "scenes"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    novel_id = Column(String, ForeignKey("novels.id"), nullable=False)
    name = Column(String, nullable=False)  # 场景名称
    description = Column(Text, default="")  # 场景描述
    setting = Column(Text, default="")  # 场景设定（环境、氛围等）
    image_url = Column(String, nullable=True)  # 场景图片URL
    
    # 章节范围信息
    start_chapter = Column(Integer, nullable=True)  # 起始章节号
    end_chapter = Column(Integer, nullable=True)    # 结束章节号
    
    # 生成状态追踪
    generating_status = Column(String, nullable=True)  # pending, running, completed, failed
    scene_task_id = Column(String, nullable=True)  # 关联的任务ID
    
    # 增量更新标记
    is_incremental = Column(Boolean, default=False)  # 是否为增量更新
    source_range = Column(String, nullable=True)    # 数据来源章节范围描述
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_parsed_at = Column(DateTime(timezone=True), nullable=True)  # 最后解析时间

    novel = relationship("Novel", back_populates="scenes")