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
    # 角色生成提示词 - 用于生成角色图片
    CHARACTER = "character"
    # 场景生成提示词 - 用于生成场景图片
    SCENE = "scene"
    # 分镜拆分提示词 - 用于将章节拆分为分镜
    CHAPTER_SPLIT = "chapter_split"


# 所有提示词模板类型列表（按使用顺序排列）
PROMPT_TEMPLATE_TYPES: List[str] = [
    PromptTemplateType.STYLE,
    PromptTemplateType.CHARACTER_PARSE,
    PromptTemplateType.SCENE_PARSE,
    PromptTemplateType.CHARACTER,
    PromptTemplateType.SCENE,
    PromptTemplateType.CHAPTER_SPLIT,
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
    PromptTemplateType.CHAPTER_SPLIT: {
        "name_key": "promptConfig.types.chapterSplit",
        "desc_key": "promptConfig.types.chapterSplitDesc",
        "icon": "BookOpen",
        "color": "cyan",
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
