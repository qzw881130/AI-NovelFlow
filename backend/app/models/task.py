from sqlalchemy import Column, String, DateTime, Integer, Text, Float
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    type = Column(String, nullable=False)  # character_portrait, shot_image, shot_video, chapter_video
    status = Column(String, default="pending")  # pending, running, completed, failed
    
    # 关联信息
    novel_id = Column(String, nullable=True)
    chapter_id = Column(String, nullable=True)
    character_id = Column(String, nullable=True)
    scene_id = Column(String, nullable=True)  # 场景ID
    
    # 任务详情
    name = Column(String, nullable=False)  # 任务名称
    description = Column(Text, nullable=True)  # 任务描述
    
    # 进度信息
    progress = Column(Integer, default=0)  # 0-100
    current_step = Column(String, nullable=True)  # 当前步骤
    
    # 结果信息
    result_url = Column(String, nullable=True)  # 生成结果的URL
    error_message = Column(Text, nullable=True)  # 错误信息
    
    # ComfyUI相关
    comfyui_prompt_id = Column(String, nullable=True)  # ComfyUI的任务ID
    
    # 工作流信息（记录执行时使用的 workflow）
    workflow_id = Column(String, nullable=True)  # 执行时使用的 workflow ID
    workflow_name = Column(String, nullable=True)  # 执行时使用的 workflow 名称
    workflow_json = Column(Text, nullable=True)  # 执行时提交给ComfyUI的完整工作流JSON
    prompt_text = Column(Text, nullable=True)  # 执行时使用的提示词
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
