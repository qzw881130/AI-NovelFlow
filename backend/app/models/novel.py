from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey, Boolean, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Novel(Base):
    __tablename__ = "novels"

    id = Column(String, primary_key=True, default=generate_uuid)
    title = Column(String, nullable=False, index=True)  # 常用查询
    author = Column(String, default="")
    description = Column(Text, default="")
    cover = Column(String, nullable=True)
    status = Column(String, default="pending", index=True)  # 状态过滤
    chapter_count = Column(Integer, default=0)
    is_preset = Column(Boolean, default=False, index=True)  # 预设过滤
    prompt_template_id = Column(String, nullable=True, index=True)  # 模板关联
    chapter_split_prompt_template_id = Column(String, nullable=True)
    aspect_ratio = Column(String, default="16:9")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="novel", cascade="all, delete-orphan")
    scenes = relationship("Scene", back_populates="novel", cascade="all, delete-orphan")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(String, primary_key=True, default=generate_uuid)
    novel_id = Column(String, ForeignKey("novels.id"), nullable=False, index=True)  # 外键索引
    number = Column(Integer, nullable=False, index=True)  # 章节号查询
    title = Column(String, nullable=False)
    content = Column(Text, default="")
    status = Column(String, default="pending", index=True)  # 状态过滤
    progress = Column(Integer, default=0)
    parsed_data = Column(Text, nullable=True)
    character_images = Column(Text, nullable=True)
    shot_images = Column(Text, nullable=True)
    shot_videos = Column(Text, nullable=True)
    transition_videos = Column(Text, nullable=True)
    final_video = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    novel = relationship("Novel", back_populates="chapters")


# 复合索引：按小说查询章节时常用
Index('ix_chapters_novel_number', Chapter.novel_id, Chapter.number)


class Character(Base):
    __tablename__ = "characters"

    id = Column(String, primary_key=True, default=generate_uuid)
    novel_id = Column(String, ForeignKey("novels.id"), nullable=False, index=True)  # 外键索引
    name = Column(String, nullable=False, index=True)  # 名称查询
    description = Column(Text, default="")
    appearance = Column(Text, default="")
    image_url = Column(String, nullable=True)
    
    # 章节范围信息
    start_chapter = Column(Integer, nullable=True)
    end_chapter = Column(Integer, nullable=True)
    
    # 生成状态追踪
    generating_status = Column(String, nullable=True, index=True)  # 状态查询
    portrait_task_id = Column(String, nullable=True)
    
    # 增量更新标记
    is_incremental = Column(Boolean, default=False)
    source_range = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_parsed_at = Column(DateTime(timezone=True), nullable=True)

    novel = relationship("Novel", back_populates="characters")


# 复合索引：按小说+名称查询角色
Index('ix_characters_novel_name', Character.novel_id, Character.name)


class Scene(Base):
    __tablename__ = "scenes"

    id = Column(String, primary_key=True, default=generate_uuid)
    novel_id = Column(String, ForeignKey("novels.id"), nullable=False, index=True)  # 外键索引
    name = Column(String, nullable=False, index=True)  # 名称查询
    description = Column(Text, default="")
    setting = Column(Text, default="")
    image_url = Column(String, nullable=True)
    
    # 章节范围信息
    start_chapter = Column(Integer, nullable=True)
    end_chapter = Column(Integer, nullable=True)
    
    # 生成状态追踪
    generating_status = Column(String, nullable=True, index=True)  # 状态查询
    scene_task_id = Column(String, nullable=True)
    
    # 增量更新标记
    is_incremental = Column(Boolean, default=False)
    source_range = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_parsed_at = Column(DateTime(timezone=True), nullable=True)

    novel = relationship("Novel", back_populates="scenes")


# 复合索引：按小说+名称查询场景
Index('ix_scenes_novel_name', Scene.novel_id, Scene.name)
