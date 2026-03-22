"""分镜相关的 Pydantic Schema 定义"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal


class DialogueData(BaseModel):
    """台词数据"""

    type: Optional[Literal["character", "narration"]] = Field(
        "character", description="台词类型：character 或 narration"
    )
    order: Optional[int] = Field(None, ge=0, description="时序序号（非负整数）")
    character_name: str = Field(..., description="角色名称")
    text: str = Field(..., description="台词文本")
    emotion_prompt: Optional[str] = Field(None, description="情感提示词")
    audio_url: Optional[str] = Field(None, description="音频URL")
    audio_task_id: Optional[str] = Field(None, description="音频生成任务ID")
    audio_source: Optional[str] = Field(
        None, description="音频来源：ai_generated 或 uploaded"
    )


class KeyframeData(BaseModel):
    """关键帧数据"""

    frame_index: int = Field(..., ge=0, description="帧序号（从0开始）")
    description: str = Field(..., description="关键帧描述")
    image_url: Optional[str] = Field(None, description="图片URL")
    image_task_id: Optional[str] = Field(None, description="图片生成任务ID")
    reference_image_url: Optional[str] = Field(
        None, description="参考图片URL，null表示不使用参考图"
    )


class ShotAudioRequest(BaseModel):
    """单分镜音频生成请求"""

    dialogues: List[DialogueData] = Field(..., description="台词列表")


class BatchShotAudioRequest(BaseModel):
    """批量章节音频生成请求"""

    pass


class TransitionVideoRequest(BaseModel):
    """生成转场视频请求"""

    from_index: int = Field(..., ge=1, description="起始分镜索引(1-based)")
    to_index: int = Field(..., ge=1, description="结束分镜索引(1-based)")
    frame_count: int = Field(49, description="总帧数（8的倍数+1）")
    workflow_id: Optional[str] = Field(None, description="指定工作流ID")


class BatchTransitionRequest(BaseModel):
    """批量生成转场视频请求"""

    frame_count: int = Field(49, description="总帧数（8的倍数+1）")
    workflow_id: Optional[str] = Field(None, description="指定工作流ID")


class MergeVideosRequest(BaseModel):
    """合并视频请求"""

    include_transitions: bool = Field(False, description="是否包含转场视频")


class ShotUpdate(BaseModel):
    """分镜更新请求"""

    description: Optional[str] = Field(None, description="分镜描述")
    video_description: Optional[str] = Field(None, description="视频生成提示词")
    characters: Optional[List[str]] = Field(None, description="角色名称列表")
    scene: Optional[str] = Field(None, description="场景名称")
    props: Optional[List[str]] = Field(None, description="道具名称列表")
    duration: Optional[int] = Field(None, ge=1, le=60, description="时长（秒）")
    dialogues: Optional[List[dict]] = Field(None, description="台词数据")
    keyframes: Optional[List[dict]] = Field(None, description="关键帧数据")
    reference_audio_url: Optional[str] = Field(None, description="参考音频URL")
    insert_index: Optional[int] = Field(None, ge=1, description="插入位置（仅创建分镜时使用）")


class ShotResponse(BaseModel):
    """分镜响应"""

    id: str
    chapterId: str
    index: int
    description: str
    video_description: Optional[str] = None
    characters: List[str]
    scene: str
    props: List[str]
    duration: int
    imageUrl: Optional[str] = None
    imagePath: Optional[str] = None
    imageStatus: str
    imageTaskId: Optional[str] = None
    videoUrl: Optional[str] = None
    videoStatus: str
    videoTaskId: Optional[str] = None
    mergedCharacterImage: Optional[str] = None
    dialogues: List[dict]
    keyframes: List[dict] = []
    referenceAudioUrl: Optional[str] = None
    referenceAudioType: str = "none"
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

    class Config:
        from_attributes = True


class PatchChapterResourcesRequest(BaseModel):
    """章节资源更新请求"""

    characters: List[str] = Field(default_factory=list, description="角色名称列表")
    scenes: List[str] = Field(default_factory=list, description="场景名称列表")
    props: List[str] = Field(default_factory=list, description="道具名称列表")


class BatchShotsUpdateRequest(BaseModel):
    """批量分镜更新请求"""

    shots: List[dict] = Field(..., description="分镜数据列表，每个包含 id 和要更新的字段")


class GenerateKeyframeDescriptionsRequest(BaseModel):
    """生成关键帧描述请求"""

    count: int = Field(3, ge=1, le=10, description="要生成的关键帧数量")


class SetReferenceImageRequest(BaseModel):
    """设置参考图请求"""

    mode: Literal["auto_select", "custom", "none"] = Field(
        ..., description="模式：auto_select(自动选择)、custom(自定义)、none(不使用)"
    )
    reference_url: Optional[str] = Field(None, description="自定义参考图URL（mode为custom时使用）")


class SetReferenceAudioRequest(BaseModel):
    """设置参考音频请求"""

    mode: Literal["none", "merged", "uploaded", "character"] = Field(
        ..., description="模式：none(无)、merged(合并台词)、uploaded(上传)、character(角色音色)"
    )
    character_name: Optional[str] = Field(None, description="角色名称（mode为character时使用）")


class GenerateVideoRequest(BaseModel):
    """生成视频请求"""

    use_keyframes: bool = Field(True, description="是否使用关键帧（如果存在）")
    use_reference_audio: bool = Field(True, description="是否使用参考音频（如果存在）")
    workflow_id: Optional[str] = Field(None, description="指定工作流ID")
