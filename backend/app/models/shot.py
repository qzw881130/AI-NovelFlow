from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Shot(Base):
    """分镜模型 - 存储独立的分镜数据"""
    __tablename__ = "shots"

    id = Column(String, primary_key=True, default=generate_uuid)
    chapter_id = Column(String, ForeignKey("chapters.id"), nullable=False, index=True)
    index = Column(Integer, nullable=False, index=True)  # 分镜序号（1-based）

    # 基础信息
    description = Column(Text, default="")
    video_description = Column(Text, default="")  # 视频生成提示词
    characters = Column(Text, default="[]")  # JSON array: ["角色 1", "角色 2"]
    scene = Column(String, default="")
    props = Column(Text, default="[]")  # JSON array: ["道具 1"]
    duration = Column(Integer, default=4)  # 时长（秒）

    # 图片资源
    image_url = Column(String, nullable=True)
    image_path = Column(String, nullable=True)
    image_status = Column(String, default="pending", index=True)  # pending/generating/completed/failed
    image_task_id = Column(String, nullable=True)

    # 视频资源
    video_url = Column(String, nullable=True)
    video_status = Column(String, default="pending", index=True)  # pending/generating/completed/failed
    video_task_id = Column(String, nullable=True)

    # 角色图
    merged_character_image = Column(String, nullable=True)

    # 台词音频 (JSON array)
    # 结构：[{"character_name": "角色 1", "text": "台词内容", "audio_url": "...", "audio_source": "generated", "audio_task_id": "..."}]
    dialogues = Column(Text, default="[]")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    chapter = relationship("Chapter", back_populates="shots")


# 复合索引：按章节查询分镜时常用
Index('ix_shots_chapter_index', Shot.chapter_id, Shot.index)
