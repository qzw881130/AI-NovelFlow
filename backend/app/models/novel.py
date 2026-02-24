from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Novel(Base):
    __tablename__ = "novels"

    id = Column(String, primary_key=True, default=generate_uuid)
    title = Column(String, nullable=False)
    author = Column(String, default="")
    description = Column(Text, default="")
    cover = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, processing, completed
    chapter_count = Column(Integer, default=0)
    is_preset = Column(Boolean, default=False)  # 是否预设测试用例小说
    prompt_template_id = Column(String, nullable=True)  # 关联的人设提示词模板ID
    chapter_split_prompt_template_id = Column(String, nullable=True)  # 关联的章节拆分提示词模板ID
    aspect_ratio = Column(String, default="16:9")  # 画面比例: 16:9, 9:16, 4:3, 3:4, 1:1, 21:9, 2.35:1
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="novel", cascade="all, delete-orphan")
    scenes = relationship("Scene", back_populates="novel", cascade="all, delete-orphan")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(String, primary_key=True, default=generate_uuid)
    novel_id = Column(String, ForeignKey("novels.id"), nullable=False)
    number = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, default="")
    status = Column(String, default="pending")
    progress = Column(Integer, default=0)
    parsed_data = Column(Text, nullable=True)  # JSON string
    character_images = Column(Text, nullable=True)  # JSON array
    shot_images = Column(Text, nullable=True)  # JSON array
    shot_videos = Column(Text, nullable=True)  # JSON array
    transition_videos = Column(Text, nullable=True)  # JSON object: {"1-2": url, "2-3": url, ...}
    final_video = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    novel = relationship("Novel", back_populates="chapters")


class Character(Base):
    __tablename__ = "characters"

    id = Column(String, primary_key=True, default=generate_uuid)
    novel_id = Column(String, ForeignKey("novels.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    appearance = Column(Text, default="")
    image_url = Column(String, nullable=True)
    
    # 章节范围信息
    start_chapter = Column(Integer, nullable=True)  # 起始章节号
    end_chapter = Column(Integer, nullable=True)    # 结束章节号
    
    # 生成状态追踪
    generating_status = Column(String, nullable=True)  # pending, running, completed, failed
    portrait_task_id = Column(String, nullable=True)  # 关联的任务ID
    
    # 增量更新标记
    is_incremental = Column(Boolean, default=False)  # 是否为增量更新
    source_range = Column(String, nullable=True)    # 数据来源章节范围描述
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_parsed_at = Column(DateTime(timezone=True), nullable=True)  # 最后解析时间

    novel = relationship("Novel", back_populates="characters")


class Scene(Base):
    __tablename__ = "scenes"

    id = Column(String, primary_key=True, default=generate_uuid)
    novel_id = Column(String, ForeignKey("novels.id"), nullable=False)
    name = Column(String, nullable=False)  # 场景名称
    description = Column(Text, default="")  # 场景描述
    setting = Column(Text, default="")  # 环境设置/布景描述（用于生成图片）
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
