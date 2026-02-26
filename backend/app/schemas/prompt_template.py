"""
PromptTemplate Schema 层

定义提示词模板相关的请求/响应数据模型
"""
from pydantic import BaseModel
from typing import Optional


class PromptTemplateCreate(BaseModel):
    """创建提示词模板请求"""
    name: str
    description: str = ""
    template: str
    type: str = "character"  # style, character_parse, scene_parse, character, scene, chapter_split


class PromptTemplateUpdate(BaseModel):
    """更新提示词模板请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    template: Optional[str] = None
    type: Optional[str] = None


class PromptTemplateResponse(BaseModel):
    """提示词模板响应"""
    id: str
    name: str
    description: str
    template: str
    type: str
    isSystem: bool
    isActive: bool
    createdAt: str

    class Config:
        from_attributes = True
