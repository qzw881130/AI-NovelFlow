"""角色相关的 Pydantic Schema 定义"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CharacterBase(BaseModel):
    """角色基础字段"""
    novel_id: str = Field(..., alias="novelId", description="关联的小说 ID")
    name: str = Field(..., description="角色名称")
    description: Optional[str] = Field("", description="角色描述")
    appearance: Optional[str] = Field("", description="外貌描述")
    voice_prompt: Optional[str] = Field("", description="音色提示词描述")
    is_narrator: Optional[bool] = Field(False, description="是否为旁白角色")


class CharacterCreate(CharacterBase):
    """创建角色请求"""
    model_config = {"populate_by_name": True}


class CharacterUpdate(BaseModel):
    """更新角色请求"""
    name: Optional[str] = Field(None, description="角色名称")
    description: Optional[str] = Field(None, description="角色描述")
    appearance: Optional[str] = Field(None, description="外貌描述")
    voice_prompt: Optional[str] = Field(None, description="音色提示词描述")
    is_narrator: Optional[bool] = Field(None, description="是否为旁白角色")


class CharacterResponse(CharacterBase):
    """角色响应"""
    id: str
    image_url: Optional[str] = None
    reference_audio_url: Optional[str] = None
    generating_status: Optional[str] = None
    portrait_task_id: Optional[str] = None
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None
    is_incremental: bool = False
    source_range: Optional[str] = None
    is_narrator: bool = False
    last_parsed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
