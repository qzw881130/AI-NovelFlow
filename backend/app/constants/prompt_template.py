"""
提示词模板类型常量定义

定义所有提示词模板类型及其显示名称、描述的国际化键
"""

from typing import Dict, List


# ==================== 提示词模板类型定义 ====================

class PromptTemplateType:
    """提示词模板类型"""
    # 风格提示词 - 用于图片生成的风格描述（独立模板类型，不再是属性）
    STYLE = "style"
    # 角色解析提示词 - 用于从小说文本中解析角色信息
    CHARACTER_PARSE = "character_parse"
    # 场景解析提示词 - 用于从小说文本中解析场景信息
    SCENE_PARSE = "scene_parse"
    # 道具解析提示词 - 用于从小说文本中解析道具信息
    PROP_PARSE = "prop_parse"
    # 角色生成提示词 - 用于生成角色图片
    CHARACTER = "character"
    # 场景生成提示词 - 用于生成场景图片
    SCENE = "scene"
    # 道具生成提示词 - 用于生成道具图片
    PROP = "prop"
    # 分镜拆分提示词 - 用于将章节拆分为分镜
    CHAPTER_SPLIT = "chapter_split"
    # 关键帧描述提示词 - 用于生成分镜关键帧描述
    KEYFRAME_DESCRIPTION = "keyframe_description"
    # 分镜图提示词 - 用于构建主分镜图最终提示词
    SHOT_IMAGE_PROMPT = "shot_image_prompt"
    # 视频生成模式推荐提示词
    VIDEO_MODE_RECOMMENDER = "video_mode_recommender"
    # 关键帧规划提示词
    KEYFRAME_PLANNER = "keyframe_planner"
    # 关键帧生图提示词
    KEYFRAME_IMAGE_PROMPT = "keyframe_image_prompt"
    # 关键帧过渡规划提示词
    KEYFRAME_TRANSITION = "keyframe_transition"
    # MiniMax H3 单帧视频提示词
    H3_SINGLE_FRAME_PROMPT = "h3_single_frame_prompt"
    # MiniMax H3 首尾帧视频提示词
    H3_FIRST_LAST_FRAME_PROMPT = "h3_first_last_frame_prompt"
    # MiniMax H3 多关键帧视频提示词
    H3_MULTI_KEYFRAME_PROMPT = "h3_multi_keyframe_prompt"


# 所有提示词模板类型列表（按使用顺序排列）
PROMPT_TEMPLATE_TYPES: List[str] = [
    PromptTemplateType.STYLE,
    PromptTemplateType.CHARACTER_PARSE,
    PromptTemplateType.SCENE_PARSE,
    PromptTemplateType.PROP_PARSE,
    PromptTemplateType.CHARACTER,
    PromptTemplateType.SCENE,
    PromptTemplateType.PROP,
    PromptTemplateType.CHAPTER_SPLIT,
    PromptTemplateType.SHOT_IMAGE_PROMPT,
    PromptTemplateType.VIDEO_MODE_RECOMMENDER,
    PromptTemplateType.KEYFRAME_DESCRIPTION,
    PromptTemplateType.KEYFRAME_PLANNER,
    PromptTemplateType.KEYFRAME_IMAGE_PROMPT,
    PromptTemplateType.KEYFRAME_TRANSITION,
    PromptTemplateType.H3_SINGLE_FRAME_PROMPT,
    PromptTemplateType.H3_FIRST_LAST_FRAME_PROMPT,
    PromptTemplateType.H3_MULTI_KEYFRAME_PROMPT,
]


# 提示词模板类型配置（包含显示名称和描述的国际化键）
PROMPT_TEMPLATE_TYPE_CONFIG: Dict[str, Dict] = {
    PromptTemplateType.STYLE: {
        "name_key": "promptConfig.types.style",
        "desc_key": "promptConfig.types.styleDesc",
        "icon": "Palette",
        "color": "pink",
    },
    PromptTemplateType.CHARACTER_PARSE: {
        "name_key": "promptConfig.types.characterParse",
        "desc_key": "promptConfig.types.characterParseDesc",
        "icon": "Users",
        "color": "blue",
    },
    PromptTemplateType.SCENE_PARSE: {
        "name_key": "promptConfig.types.sceneParse",
        "desc_key": "promptConfig.types.sceneParseDesc",
        "icon": "MapPin",
        "color": "green",
    },
    PromptTemplateType.CHARACTER: {
        "name_key": "promptConfig.types.character",
        "desc_key": "promptConfig.types.characterDesc",
        "icon": "User",
        "color": "purple",
    },
    PromptTemplateType.SCENE: {
        "name_key": "promptConfig.types.scene",
        "desc_key": "promptConfig.types.sceneDesc",
        "icon": "Image",
        "color": "orange",
    },
    PromptTemplateType.PROP_PARSE: {
        "name_key": "promptConfig.types.propParse",
        "desc_key": "promptConfig.types.propParseDesc",
        "icon": "Package",
        "color": "yellow",
    },
    PromptTemplateType.CHAPTER_SPLIT: {
        "name_key": "promptConfig.types.chapterSplit",
        "desc_key": "promptConfig.types.chapterSplitDesc",
        "icon": "BookOpen",
        "color": "cyan",
    },
    PromptTemplateType.PROP: {
        "name_key": "promptConfig.types.prop",
        "desc_key": "promptConfig.types.propDesc",
        "icon": "Box",
        "color": "amber",
    },
    PromptTemplateType.KEYFRAME_DESCRIPTION: {
        "name_key": "promptConfig.types.keyframeDescription",
        "desc_key": "promptConfig.types.keyframeDescriptionDesc",
        "icon": "Film",
        "color": "indigo",
    },
    PromptTemplateType.SHOT_IMAGE_PROMPT: {
        "name_key": "promptConfig.types.shotImagePrompt",
        "desc_key": "promptConfig.types.shotImagePromptDesc",
        "icon": "Image",
        "color": "cyan",
    },
    PromptTemplateType.VIDEO_MODE_RECOMMENDER: {
        "name_key": "promptConfig.types.videoModeRecommender",
        "desc_key": "promptConfig.types.videoModeRecommenderDesc",
        "icon": "SlidersHorizontal",
        "color": "violet",
    },
    PromptTemplateType.KEYFRAME_PLANNER: {
        "name_key": "promptConfig.types.keyframePlanner",
        "desc_key": "promptConfig.types.keyframePlannerDesc",
        "icon": "Film",
        "color": "indigo",
    },
    PromptTemplateType.KEYFRAME_IMAGE_PROMPT: {
        "name_key": "promptConfig.types.keyframeImagePrompt",
        "desc_key": "promptConfig.types.keyframeImagePromptDesc",
        "icon": "Images",
        "color": "emerald",
    },
    PromptTemplateType.KEYFRAME_TRANSITION: {
        "name_key": "promptConfig.types.keyframeTransition",
        "desc_key": "promptConfig.types.keyframeTransitionDesc",
        "icon": "Route",
        "color": "violet",
    },
    PromptTemplateType.H3_SINGLE_FRAME_PROMPT: {
        "name_key": "promptConfig.types.h3SingleFramePrompt",
        "desc_key": "promptConfig.types.h3SingleFramePromptDesc",
        "icon": "Video",
        "color": "rose",
    },
    PromptTemplateType.H3_FIRST_LAST_FRAME_PROMPT: {
        "name_key": "promptConfig.types.h3FirstLastFramePrompt",
        "desc_key": "promptConfig.types.h3FirstLastFramePromptDesc",
        "icon": "Video",
        "color": "rose",
    },
    PromptTemplateType.H3_MULTI_KEYFRAME_PROMPT: {
        "name_key": "promptConfig.types.h3MultiKeyframePrompt",
        "desc_key": "promptConfig.types.h3MultiKeyframePromptDesc",
        "icon": "Video",
        "color": "rose",
    },
}


def get_template_type_name_key(template_type: str) -> str:
    """获取模板类型的名称国际化键"""
    config = PROMPT_TEMPLATE_TYPE_CONFIG.get(template_type, {})
    return config.get("name_key", f"promptConfig.types.{template_type}")


def get_template_type_desc_key(template_type: str) -> str:
    """获取模板类型的描述国际化键"""
    config = PROMPT_TEMPLATE_TYPE_CONFIG.get(template_type, {})
    return config.get("desc_key", f"promptConfig.types.{template_type}Desc")


def get_template_type_icon(template_type: str) -> str:
    """获取模板类型的图标名称"""
    config = PROMPT_TEMPLATE_TYPE_CONFIG.get(template_type, {})
    return config.get("icon", "FileText")


def get_template_type_color(template_type: str) -> str:
    """获取模板类型的颜色"""
    config = PROMPT_TEMPLATE_TYPE_CONFIG.get(template_type, {})
    return config.get("color", "gray")
