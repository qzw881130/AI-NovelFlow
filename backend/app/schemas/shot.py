"""分镜相关的 Pydantic Schema 定义"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal


VideoMode = Literal["SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"]


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


class GenerateShotImageRequest(BaseModel):
    """生成分镜图片请求"""

    prompt_text: Optional[str] = Field(None, description="已确认的最终生图提示词；为空时由 LLM 生成")
    workflow_type: Optional[Literal["shot", "shot_scene", "shot_character_scene", "shot_scene_prop"]] = Field(
        None, description="分镜生图工作流类型；为空时使用角色+场景+道具"
    )


class ShotImageEditRequest(BaseModel):
    """编辑分镜图片请求"""

    prompt: str = Field(..., min_length=1, description="单图编辑提示词")


class ShotImageReplaceRequest(BaseModel):
    """替换分镜图片请求"""

    image_url: str = Field(..., description="编辑结果图片URL")


class BatchShotAudioRequest(BaseModel):
    """批量章节音频生成请求"""

    pass


class TransitionVideoRequest(BaseModel):
    """生成转场视频请求"""

    from_index: int = Field(..., ge=1, description="起始分镜索引(1-based)")
    to_index: int = Field(..., ge=1, description="结束分镜索引(1-based)")
    duration_seconds: Optional[float] = Field(None, gt=0, description="转场时长秒数")
    frame_count: int = Field(49, description="总帧数（8的倍数+1）")
    workflow_id: Optional[str] = Field(None, description="指定工作流ID")


class BatchTransitionRequest(BaseModel):
    """批量生成转场视频请求"""

    duration_seconds: Optional[float] = Field(None, gt=0, description="转场时长秒数")
    frame_count: int = Field(49, description="总帧数（8的倍数+1）")
    workflow_id: Optional[str] = Field(None, description="指定工作流ID")


class MergeVideosRequest(BaseModel):
    """合并视频请求"""

    mode: Optional[Literal["shots_only", "shots_with_transitions"]] = Field(
        None, description="合并模式"
    )
    include_transitions: bool = Field(False, description="是否包含转场视频（兼容旧请求）")


class ShotUpdate(BaseModel):
    """分镜更新请求"""

    description: Optional[str] = Field(None, description="分镜描述")
    video_description: Optional[str] = Field(None, description="视频生成提示词")
    shot_image_prompt: Optional[str] = Field(None, description="主分镜图最终生图提示词")
    characters: Optional[List[str]] = Field(None, description="角色名称列表")
    scene: Optional[str] = Field(None, description="场景名称")
    props: Optional[List[str]] = Field(None, description="道具名称列表")
    duration: Optional[int] = Field(None, ge=1, le=180, description="时长（秒）")
    continuity_mode: Optional[Literal["NORMAL", "CONTINUOUS_TAKE"]] = Field(
        None, description="连续模式：NORMAL 或 CONTINUOUS_TAKE"
    )
    video_director_plan: Optional[dict] = Field(None, description="视频导演规划数据")
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
    shotImagePrompt: Optional[str] = None
    characters: List[str]
    scene: str
    props: List[str]
    duration: int
    continuity_mode: str = "NORMAL"
    videoDirectorPlan: dict = {}
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


class GenerateKeyframeImageRequest(BaseModel):
    """生成关键帧图片请求"""

    workflow_id: Optional[str] = Field(None, description="指定工作流ID")
    skip_llm_when_prompt_exists: bool = Field(False, description="已有关键帧生图提示词时跳过 LLM，直接提交工作流")


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
    selected_mode: Optional[VideoMode] = Field(None, description="视频导演选择的生成模式")
    skip_llm_when_prompt_exists: bool = Field(False, description="已有最终视频提示词时跳过 LLM，直接提交工作流")


class GenerateVideoDirectorClipRequest(BaseModel):
    """重新生成单个 Video Director Clip 请求"""

    use_reference_audio: bool = Field(True, description="是否使用参考音频（如果存在）")
    auto_merge: bool = Field(True, description="Clip 生成成功后是否自动重新合并 Shot 视频")


class SaveVideoDirectorPlanRequest(BaseModel):
    """保存视频导演规划请求"""

    selected_mode: Optional[VideoMode] = None
    recommended_mode: Optional[VideoMode] = None
    recommendation_reason: Optional[str] = None
    keyframes: Optional[List[dict]] = None
    transitions: Optional[List[dict]] = None
    clips: Optional[List[dict]] = None
    execution_windows: Optional[List[dict]] = None
    window_plans: Optional[List[dict]] = None
    validation: Optional[dict] = None


class RecommendVideoModeRequest(BaseModel):
    """推荐视频生成模式请求"""

    force: bool = Field(False, description="是否强制重新推荐")


class PlanVideoKeyframesRequest(BaseModel):
    """规划视频关键帧时间轴请求"""

    force: bool = Field(False, description="是否强制重新规划关键帧时间轴")
