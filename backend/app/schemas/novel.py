from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class NovelBase(BaseModel):
    title: str
    author: str = ""
    description: str = ""
    prompt_template_id: Optional[str] = None
    chapter_split_prompt_template_id: Optional[str] = None
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
    prompt_template_id: Optional[str] = None
    chapter_split_prompt_template_id: Optional[str] = None
    aspect_ratio: Optional[str] = "16:9"
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
