from sqlalchemy import Column, String, DateTime, Integer, Text, Float, Index
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    type = Column(String, nullable=False, index=True)  # 类型查询
    status = Column(String, default="pending", index=True)  # 状态查询
    
    # 关联信息
    novel_id = Column(String, nullable=True, index=True)  # 外键关联
    chapter_id = Column(String, nullable=True, index=True)
    character_id = Column(String, nullable=True, index=True)
    scene_id = Column(String, nullable=True, index=True)
    
    # 任务详情
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    
    # 进度信息
    progress = Column(Integer, default=0)  # 0-100
    current_step = Column(String, nullable=True)
    
    # 结果信息
    result_url = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # ComfyUI相关
    comfyui_prompt_id = Column(String, nullable=True, index=True)  # ComfyUI 任务查询
    
    # 工作流信息
    workflow_id = Column(String, nullable=True)
    workflow_name = Column(String, nullable=True)
    workflow_json = Column(Text, nullable=True)
    prompt_text = Column(Text, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# 复合索引：按小说+类型+状态查询任务
Index('ix_tasks_novel_type_status', Task.novel_id, Task.type, Task.status)
# 复合索引：按状态查询待处理任务
Index('ix_tasks_status_created', Task.status, Task.created_at)
