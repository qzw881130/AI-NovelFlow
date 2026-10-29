"""
提示词模板类型常量定义

定义所有提示词模板类型及其显示名称、描述的国际化键
"""

from typing import Dict, List

# Same template type and selection UI; separate records preserve V1 and user copies.
TRANSITION_V1_NAME = "关键帧过渡规划"
TRANSITION_V2_NAME = "关键帧过渡规划（因果上下文 V2）"
TRANSITION_INPUT_V1 = "KEYFRAME_TRANSITION_VISUAL_V1"
TRANSITION_INPUT_V2 = "KEYFRAME_TRANSITION_CAUSAL_V2"
TRANSITION_CONTRACT_PREFIX = "INPUT_CONTRACT:"


# ==================== 提示词模板类型定义 ====================

class PromptTemplateType:
    """提示词模板类型"""
    STORY_WORLD_CONTEXT_RECOMMENDER = "story_world_context_recommender"
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
    # LLM 文字设定补全，不是图片生成模板
    SCENE_SETTING = "scene_setting"
    PROP_APPEARANCE = "prop_appearance"
    # 分镜拆分提示词 - 用于将章节拆分为分镜
    CHAPTER_SPLIT = "chapter_split"
    # 关键帧描述提示词 - 用于生成分镜关键帧描述
    KEYFRAME_DESCRIPTION = "keyframe_description"
    # 分镜图提示词 - 用于构建主分镜图最终提示词
    SHOT_IMAGE_PROMPT = "shot_image_prompt"
    # 关键帧规划提示词
    KEYFRAME_PLANNER = "keyframe_planner"
    # 关键帧生图提示词
    KEYFRAME_IMAGE_PROMPT = "keyframe_image_prompt"
    IMAGE_QUALITY_REVIEW_PROMPT = "image_quality_review_prompt"
    TEMPORAL_REFERENCE_SELECTOR = "temporal_reference_selector"
    # 关键帧过渡规划提示词
    KEYFRAME_TRANSITION = "keyframe_transition"
    # 视频片段执行规划提示词
    CLIP_EXECUTION_PLANNER = "clip_execution_planner"
    # MiniMax H3 多关键帧视频提示词
    H3_MULTI_KEYFRAME_PROMPT = "h3_multi_keyframe_prompt"
    H3_MULTI_KEYFRAME_DIRECTOR_PHASE_B = "h3_multi_keyframe_director_phase_b"
    H3_PREFLIGHT_REPAIR_PROMPT = "h3_preflight_repair_prompt"
    H3_EXECUTION_OPTIMIZER_PROMPT = "h3_execution_optimizer_prompt"
    GRID_SHOT_PLAN = "grid_shot_plan"
    GRID_IMAGE_PROMPT = "grid_image_prompt"
    GRID_CLIP_PLAN = "grid_clip_plan"
    GRID_H3_PHASE_B = "grid_h3_phase_b"
    BACKGROUND_MUSIC_DIRECTOR = "background_music_director"
    BACKGROUND_MUSIC_DIRECTOR_FULL = "background_music_director_full"
    BACKGROUND_MUSIC_GENERATION = "background_music_generation"
    SUBTITLE_CORRECTION = "subtitle_correction"
    SUBTITLE_TRANSLATION = "subtitle_translation"


# 所有提示词模板类型列表（按使用顺序排列）
PROMPT_TEMPLATE_TYPES: List[str] = [
    PromptTemplateType.STORY_WORLD_CONTEXT_RECOMMENDER,
    PromptTemplateType.STYLE,
    PromptTemplateType.CHARACTER_PARSE,
    PromptTemplateType.SCENE_PARSE,
    PromptTemplateType.PROP_PARSE,
    PromptTemplateType.CHARACTER,
    PromptTemplateType.SCENE,
    PromptTemplateType.PROP,
    PromptTemplateType.SCENE_SETTING,
    PromptTemplateType.PROP_APPEARANCE,
    PromptTemplateType.CHAPTER_SPLIT,
    PromptTemplateType.SHOT_IMAGE_PROMPT,
    PromptTemplateType.KEYFRAME_DESCRIPTION,
    PromptTemplateType.KEYFRAME_PLANNER,
    PromptTemplateType.KEYFRAME_IMAGE_PROMPT,
    PromptTemplateType.IMAGE_QUALITY_REVIEW_PROMPT,
    PromptTemplateType.TEMPORAL_REFERENCE_SELECTOR,
    PromptTemplateType.KEYFRAME_TRANSITION,
    PromptTemplateType.CLIP_EXECUTION_PLANNER,
    PromptTemplateType.H3_MULTI_KEYFRAME_DIRECTOR_PHASE_B,
    PromptTemplateType.GRID_SHOT_PLAN,
    PromptTemplateType.GRID_IMAGE_PROMPT,
    PromptTemplateType.GRID_CLIP_PLAN,
    PromptTemplateType.GRID_H3_PHASE_B,
    PromptTemplateType.BACKGROUND_MUSIC_DIRECTOR,
    PromptTemplateType.BACKGROUND_MUSIC_DIRECTOR_FULL,
    PromptTemplateType.BACKGROUND_MUSIC_GENERATION,
    PromptTemplateType.SUBTITLE_CORRECTION,
    PromptTemplateType.SUBTITLE_TRANSLATION,
]


# 提示词模板类型配置（包含显示名称和描述的国际化键）
PROMPT_TEMPLATE_TYPE_CONFIG: Dict[str, Dict] = {
    PromptTemplateType.GRID_SHOT_PLAN: {
        "name_key": "promptConfig.types.gridShotPlan",
        "desc_key": "promptConfig.types.gridShotPlanDesc",
        "icon": "LayoutGrid", "color": "cyan",
    },
    PromptTemplateType.GRID_IMAGE_PROMPT: {
        "name_key": "promptConfig.types.gridImagePrompt",
        "desc_key": "promptConfig.types.gridImagePromptDesc",
        "icon": "Images", "color": "cyan",
    },
    PromptTemplateType.GRID_CLIP_PLAN: {
        "name_key": "promptConfig.types.gridClipPlan",
        "desc_key": "promptConfig.types.gridClipPlanDesc",
        "icon": "Film", "color": "violet",
    },
    PromptTemplateType.GRID_H3_PHASE_B: {
        "name_key": "promptConfig.types.gridH3PhaseB",
        "desc_key": "promptConfig.types.gridH3PhaseBDesc",
        "icon": "Video", "color": "rose",
    },
    PromptTemplateType.SUBTITLE_CORRECTION: {
        "name_key": "promptConfig.types.subtitleCorrection",
        "desc_key": "promptConfig.types.subtitleCorrectionDesc",
        "icon": "FileText", "color": "blue",
    },
    PromptTemplateType.SUBTITLE_TRANSLATION: {
        "name_key": "promptConfig.types.subtitleTranslation",
        "desc_key": "promptConfig.types.subtitleTranslationDesc",
        "icon": "FileText", "color": "blue",
    },
    PromptTemplateType.BACKGROUND_MUSIC_DIRECTOR: {
        "name_key": "promptConfig.types.backgroundMusicDirector",
        "desc_key": "promptConfig.types.backgroundMusicDirectorDesc",
        "icon": "Music", "color": "violet",
    },
    PromptTemplateType.BACKGROUND_MUSIC_DIRECTOR_FULL: {
        "name_key": "promptConfig.types.backgroundMusicDirectorFull",
        "desc_key": "promptConfig.types.backgroundMusicDirectorFullDesc",
        "icon": "Music", "color": "violet",
    },
    PromptTemplateType.BACKGROUND_MUSIC_GENERATION: {
        "name_key": "promptConfig.types.backgroundMusicGeneration",
        "desc_key": "promptConfig.types.backgroundMusicGenerationDesc",
        "icon": "Music", "color": "purple",
    },
    PromptTemplateType.H3_MULTI_KEYFRAME_DIRECTOR_PHASE_B: {
        "name_key": "promptConfig.types.h3MultiKeyframeDirectorPhaseB",
        "desc_key": "promptConfig.types.h3MultiKeyframeDirectorPhaseBDesc",
        "icon": "Video", "color": "rose", "file_number": "13",
    },
    PromptTemplateType.IMAGE_QUALITY_REVIEW_PROMPT: {
        "name_key": "promptConfig.types.imageQualityReviewPrompt",
        "desc_key": "promptConfig.types.imageQualityReviewPromptDesc",
        "icon": "Images", "color": "emerald", "file_number": "15",
    },
    PromptTemplateType.SCENE_SETTING: {
        "name_key": "promptConfig.types.sceneSetting",
        "desc_key": "promptConfig.types.sceneSettingDesc",
        "icon": "FileText",
        "color": "orange",
    },
    PromptTemplateType.PROP_APPEARANCE: {
        "name_key": "promptConfig.types.propAppearance",
        "desc_key": "promptConfig.types.propAppearanceDesc",
        "icon": "FileText",
        "color": "amber",
    },
    PromptTemplateType.STORY_WORLD_CONTEXT_RECOMMENDER: {
        "name_key": "promptConfig.types.storyWorldContextRecommender",
        "desc_key": "promptConfig.types.storyWorldContextRecommenderDesc",
        "icon": "Globe2",
        "color": "teal",
        "file_number": "01",
    },
    PromptTemplateType.STYLE: {
        "name_key": "promptConfig.types.style",
        "desc_key": "promptConfig.types.styleDesc",
        "icon": "Palette",
        "color": "pink",
        "file_number": "02",
    },
    PromptTemplateType.CHARACTER_PARSE: {
        "name_key": "promptConfig.types.characterParse",
        "desc_key": "promptConfig.types.characterParseDesc",
        "icon": "Users",
        "color": "blue",
        "file_number": "03",
    },
    PromptTemplateType.SCENE_PARSE: {
        "name_key": "promptConfig.types.sceneParse",
        "desc_key": "promptConfig.types.sceneParseDesc",
        "icon": "MapPin",
        "color": "green",
        "file_number": "03",
    },
    PromptTemplateType.CHARACTER: {
        "name_key": "promptConfig.types.character",
        "desc_key": "promptConfig.types.characterDesc",
        "icon": "User",
        "color": "purple",
        "file_number": "04",
    },
    PromptTemplateType.SCENE: {
        "name_key": "promptConfig.types.scene",
        "desc_key": "promptConfig.types.sceneDesc",
        "icon": "Image",
        "color": "orange",
        "file_number": "04",
    },
    PromptTemplateType.PROP_PARSE: {
        "name_key": "promptConfig.types.propParse",
        "desc_key": "promptConfig.types.propParseDesc",
        "icon": "Package",
        "color": "yellow",
        "file_number": "03",
    },
    PromptTemplateType.CHAPTER_SPLIT: {
        "name_key": "promptConfig.types.chapterSplit",
        "desc_key": "promptConfig.types.chapterSplitDesc",
        "icon": "BookOpen",
        "color": "cyan",
        "file_number": "05",
    },
    PromptTemplateType.PROP: {
        "name_key": "promptConfig.types.prop",
        "desc_key": "promptConfig.types.propDesc",
        "icon": "Box",
        "color": "amber",
        "file_number": "04",
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
        "file_number": "06",
    },
    PromptTemplateType.KEYFRAME_PLANNER: {
        "name_key": "promptConfig.types.keyframePlanner",
        "desc_key": "promptConfig.types.keyframePlannerDesc",
        "icon": "Film",
        "color": "indigo",
        "file_number": "08",
    },
    PromptTemplateType.KEYFRAME_IMAGE_PROMPT: {
        "name_key": "promptConfig.types.keyframeImagePrompt",
        "desc_key": "promptConfig.types.keyframeImagePromptDesc",
        "icon": "Images",
        "color": "emerald",
        "file_number": "09",
    },
    PromptTemplateType.TEMPORAL_REFERENCE_SELECTOR: {
        "name_key": "promptConfig.types.temporalReferenceSelector",
        "desc_key": "promptConfig.types.temporalReferenceSelectorDesc",
        "icon": "Images",
        "color": "emerald",
        "file_number": "09A",
    },
    PromptTemplateType.KEYFRAME_TRANSITION: {
        "name_key": "promptConfig.types.keyframeTransition",
        "desc_key": "promptConfig.types.keyframeTransitionDesc",
        "icon": "Route",
        "color": "violet",
        "file_number": "10",
    },
    PromptTemplateType.CLIP_EXECUTION_PLANNER: {
        "name_key": "promptConfig.types.clipExecutionPlanner",
        "desc_key": "promptConfig.types.clipExecutionPlannerDesc",
        "icon": "Route",
        "color": "violet",
    },
}

# Prompt applicability is part of the type contract; it is not a new database field.
GRID_PROMPT_TYPES = frozenset({
    PromptTemplateType.GRID_SHOT_PLAN, PromptTemplateType.GRID_IMAGE_PROMPT,
    PromptTemplateType.GRID_CLIP_PLAN, PromptTemplateType.GRID_H3_PHASE_B,
})
SHARED_PROMPT_TYPES = frozenset({
    PromptTemplateType.STORY_WORLD_CONTEXT_RECOMMENDER, PromptTemplateType.STYLE,
    PromptTemplateType.CHARACTER_PARSE, PromptTemplateType.SCENE_PARSE,
    PromptTemplateType.PROP_PARSE, PromptTemplateType.CHARACTER,
    PromptTemplateType.SCENE, PromptTemplateType.PROP,
    PromptTemplateType.SCENE_SETTING, PromptTemplateType.PROP_APPEARANCE,
    PromptTemplateType.BACKGROUND_MUSIC_DIRECTOR,
    PromptTemplateType.BACKGROUND_MUSIC_DIRECTOR_FULL,
    PromptTemplateType.BACKGROUND_MUSIC_GENERATION,
    PromptTemplateType.SUBTITLE_CORRECTION, PromptTemplateType.SUBTITLE_TRANSLATION,
})


def prompt_template_scope(template_type: str) -> str:
    if template_type in GRID_PROMPT_TYPES:
        return "grid"
    if template_type in SHARED_PROMPT_TYPES:
        return "shared"
    if template_type in PROMPT_TEMPLATE_TYPES:
        return "single"
    raise ValueError(f"UNKNOWN_PROMPT_TEMPLATE_TYPE: {template_type}")

PROMPT_TEMPLATE_FILE_NUMBERS = {
    template_type: config["file_number"]
    for template_type, config in PROMPT_TEMPLATE_TYPE_CONFIG.items()
    if config.get("file_number")
}

# The novel stores references to versions, never prompt bodies. Keep this map in
# registry order so copying and runtime resolution cover every selectable type.
NOVEL_PROMPT_TEMPLATE_FIELDS = {
    "story_world_context_recommender": "story_world_context_prompt_template_id",
    "style": "style_prompt_template_id",
    "character_parse": "character_parse_prompt_template_id",
    "scene_parse": "scene_parse_prompt_template_id",
    "prop_parse": "prop_parse_prompt_template_id",
    "character": "prompt_template_id",
    "scene": "scene_prompt_template_id",
    "prop": "prop_prompt_template_id",
    "scene_setting": "scene_setting_prompt_template_id",
    "prop_appearance": "prop_appearance_prompt_template_id",
    "chapter_split": "chapter_split_prompt_template_id",
    "shot_image_prompt": "shot_image_prompt_template_id",
    "keyframe_description": "keyframe_description_prompt_template_id",
    "keyframe_planner": "keyframe_planner_prompt_template_id",
    "keyframe_image_prompt": "keyframe_image_prompt_template_id",
    "image_quality_review_prompt": "image_quality_review_prompt_template_id",
    "temporal_reference_selector": "temporal_reference_selector_prompt_template_id",
    "keyframe_transition": "keyframe_transition_prompt_template_id",
    "clip_execution_planner": "clip_execution_planner_prompt_template_id",
    "h3_multi_keyframe_prompt": "h3_multi_keyframe_prompt_template_id",
    "h3_multi_keyframe_director_phase_b": "h3_multi_keyframe_director_phase_b_template_id",
    "h3_execution_optimizer_prompt": "h3_execution_optimizer_prompt_template_id",
    "h3_preflight_repair_prompt": "h3_preflight_repair_prompt_template_id",
    "grid_shot_plan": "grid_shot_plan_prompt_template_id",
    "grid_image_prompt": "grid_image_prompt_template_id",
    "grid_clip_plan": "grid_clip_plan_prompt_template_id",
    "grid_h3_phase_b": "grid_h3_phase_b_prompt_template_id",
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
