from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class NovelBase(BaseModel):
    title: str
    author: str = ""
    description: str = ""
    # 提示词模板关联（每种类型可选择不同模板）
    style_prompt_template_id: Optional[str] = None  # 风格提示词模板
    character_parse_prompt_template_id: Optional[str] = None  # 角色解析提示词模板
    scene_parse_prompt_template_id: Optional[str] = None  # 场景解析提示词模板
    prompt_template_id: Optional[str] = None  # 角色生成提示词模板
    scene_prompt_template_id: Optional[str] = None  # 场景生成提示词模板
    chapter_split_prompt_template_id: Optional[str] = None  # 分镜拆分提示词模板
    aspect_ratio: Optional[str] = "16:9"


class NovelCreate(NovelBase):
    pass


class NovelUpdate(NovelBase):
    pass


class NovelResponse(NovelBase):
    id: str
    cover: Optional[str] = None
    status: str
    chapter_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChapterBase(BaseModel):
    title: str
    number: int
    content: str = ""


class ChapterCreate(ChapterBase):
    pass


class ChapterResponse(ChapterBase):
    id: str
    novel_id: str
    status: str
    progress: int
    parsed_data: Optional[str] = None
    character_images: Optional[str] = None
    shot_images: Optional[str] = None
    shot_videos: Optional[str] = None
    final_video: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CharacterBase(BaseModel):
    name: str
    description: str = ""
    appearance: str = ""


class CharacterCreate(CharacterBase):
    pass


class CharacterResponse(CharacterBase):
    id: str
    novel_id: str
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
