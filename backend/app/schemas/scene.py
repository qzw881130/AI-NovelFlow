"""场景相关的 Pydantic Schema 定义"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SceneBase(BaseModel):
    """场景基础字段"""
    novel_id: str = Field(..., alias="novelId", description="关联的小说 ID")
    name: str = Field(..., description="场景名称")
    description: Optional[str] = Field("", description="场景描述")
    setting: Optional[str] = Field("", description="环境设置")


class SceneCreate(SceneBase):
    """创建场景请求"""
    model_config = {"populate_by_name": True}


class SceneUpdate(BaseModel):
    """更新场景请求"""
    name: Optional[str] = Field(None, description="场景名称")
    description: Optional[str] = Field(None, description="场景描述")
    setting: Optional[str] = Field(None, description="环境设置")


class SceneResponse(SceneBase):
    """场景响应"""
    id: str
    image_url: Optional[str] = None
    generating_status: Optional[str] = None
    scene_task_id: Optional[str] = None
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None
    is_incremental: bool = False
    source_range: Optional[str] = None
    last_parsed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ParseScenesRequest(BaseModel):
    """解析场景请求"""
    novel_id: str = Field(..., description="小说 ID")
    chapter_ids: list[str] = Field(default=[], description="章节 ID 列表，不传则解析所有章节")
    mode: str = Field("incremental", description="解析模式：incremental 或 full")
