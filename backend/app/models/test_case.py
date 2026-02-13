from sqlalchemy import Column, String, DateTime, Integer, Text, Boolean
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)  # 测试用例名称
    description = Column(Text, nullable=True)  # 描述
    
    # 关联的小说ID
    novel_id = Column(String, nullable=False)
    
    # 测试用例类型
    type = Column(String, default="full")  # full:完整流程, character:仅角色, shot:仅分镜, video:仅视频
    
    # 状态
    is_active = Column(Boolean, default=True)  # 是否启用
    is_preset = Column(Boolean, default=False)  # 是否预设（内置）测试用例
    
    # 预期结果
    expected_character_count = Column(Integer, nullable=True)  # 预期角色数量
    expected_shot_count = Column(Integer, nullable=True)  # 预期分镜数量
    
    # 备注
    notes = Column(Text, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
