from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Any
from datetime import datetime


class NovelBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    author: str = ""
    description: str = ""
    # 提示词模板关联（每种类型可选择不同模板）
    style_prompt_template_id: Optional[str] = Field(None, alias="stylePromptTemplateId")  # 风格提示词模板
    character_parse_prompt_template_id: Optional[str] = Field(None, alias="characterParsePromptTemplateId")  # 角色解析提示词模板
    scene_parse_prompt_template_id: Optional[str] = Field(None, alias="sceneParsePromptTemplateId")  # 场景解析提示词模板
    prop_parse_prompt_template_id: Optional[str] = Field(None, alias="propParsePromptTemplateId")  # 道具解析提示词模板
    prompt_template_id: Optional[str] = Field(None, alias="promptTemplateId")  # 角色生成提示词模板
    scene_prompt_template_id: Optional[str] = Field(None, alias="scenePromptTemplateId")  # 场景生成提示词模板
    prop_prompt_template_id: Optional[str] = Field(None, alias="propPromptTemplateId")  # 道具生成提示词模板
    chapter_split_prompt_template_id: Optional[str] = Field(None, alias="chapterSplitPromptTemplateId")  # 分镜拆分提示词模板
    keyframe_description_prompt_template_id: Optional[str] = Field(None, alias="keyframeDescriptionPromptTemplateId")  # 关键帧描述提示词模板
    shot_image_prompt_template_id: Optional[str] = Field(None, alias="shotImagePromptTemplateId")  # 主分镜图提示词模板
    video_mode_recommender_prompt_template_id: Optional[str] = Field(None, alias="videoModeRecommenderPromptTemplateId")  # 视频模式推荐提示词模板
    keyframe_planner_prompt_template_id: Optional[str] = Field(None, alias="keyframePlannerPromptTemplateId")  # 关键帧规划提示词模板
    keyframe_image_prompt_template_id: Optional[str] = Field(None, alias="keyframeImagePromptTemplateId")  # 关键帧生图提示词模板
    keyframe_transition_prompt_template_id: Optional[str] = Field(None, alias="keyframeTransitionPromptTemplateId")  # 关键帧过渡规划提示词模板
    h3_single_frame_prompt_template_id: Optional[str] = Field(None, alias="h3SingleFramePromptTemplateId")  # H3 单帧视频提示词模板
    h3_first_last_frame_prompt_template_id: Optional[str] = Field(None, alias="h3FirstLastFramePromptTemplateId")  # H3 首尾帧视频提示词模板
    h3_multi_keyframe_prompt_template_id: Optional[str] = Field(None, alias="h3MultiKeyframePromptTemplateId")  # H3 多关键帧视频提示词模板
    aspect_ratio: Optional[str] = Field("16:9", alias="aspectRatio")


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


class ChapterDetailResponse(ChapterResponse):
    """章节详情响应（包含分镜数据）"""

    transition_videos: Optional[dict] = None
    shots: Optional[List[Any]] = None  # ShotResponse 列表

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
