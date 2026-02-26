"""
常量定义模块
"""
from app.constants.workflow import (
    WORKFLOW_TYPES,
    DEFAULT_WORKFLOWS,
    EXTRA_SYSTEM_WORKFLOWS,
    # 辅助函数
    get_workflow_name_key,
    get_workflow_desc_key,
    find_workflow_config_by_name,
    get_workflow_i18n_keys,
)

from app.constants.test_case import (
    # 翻译键映射
    PRESET_NAME_KEYS,
    PRESET_DESC_KEYS,
    PRESET_NOTES_KEYS,
    # 预设测试用例数据
    PRESET_TEST_CASES,
    # 小马过河
    XIAOMA_CHAPTERS,
    XIAOMA_CHARACTERS,
    XIAOMA_TEST_CASE_CONFIG,
    XIAOMA_NOVEL_CONFIG,
    # 小红帽
    REDRIDINGHOOD_CHAPTERS,
    REDRIDINGHOOD_CHARACTERS,
    REDRIDINGHOOD_TEST_CASE_CONFIG,
    REDRIDINGHOOD_NOVEL_CONFIG,
    # 皇帝的新装
    EMPEROR_CHAPTERS,
    EMPEROR_CHARACTERS,
    EMPEROR_TEST_CASE_CONFIG,
    EMPEROR_NOVEL_CONFIG,
)

from app.constants.llm import (
    # 默认参数
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT,
    DEFAULT_VIDEO_DURATION,
    # 日志字段长度限制
    LOG_SYSTEM_PROMPT_MAX_LENGTH,
    LOG_USER_PROMPT_MAX_LENGTH,
    LOG_RESPONSE_MAX_LENGTH,
    LOG_ERROR_MESSAGE_MAX_LENGTH,
    # 文本截断限制
    NOVEL_TEXT_MAX_LENGTH,
    CHAPTER_CONTENT_MAX_LENGTH,
    # 默认提示词模板
    DEFAULT_PARSE_CHARACTERS_PROMPT,
    CHAPTER_RANGE_PLACEHOLDER,
    DEFAULT_CHAPTER_RANGE_DESCRIPTION,
    DEFAULT_PARSE_SCENES_PROMPT,
    DEFAULT_VIDEO_PROMPT_EXPAND_SYSTEM,
    DEFAULT_CHARACTER_APPEARANCE_FALLBACK,
    DEFAULT_SCENE_SETTING_FALLBACK,
    # 提示词生成函数
    get_character_appearance_prompt,
    get_scene_setting_prompt,
)

from app.constants.prompt_template import (
    # 提示词模板类型
    PromptTemplateType,
    PROMPT_TEMPLATE_TYPES,
    PROMPT_TEMPLATE_TYPE_CONFIG,
    # 辅助函数
    get_template_type_name_key,
    get_template_type_desc_key,
    get_template_type_icon,
    get_template_type_color,
)

__all__ = [
    # Workflow
    "WORKFLOW_TYPES",
    "DEFAULT_WORKFLOWS",
    "EXTRA_SYSTEM_WORKFLOWS",
    "get_workflow_name_key",
    "get_workflow_desc_key",
    "find_workflow_config_by_name",
    "get_workflow_i18n_keys",
    # Test Case
    "PRESET_NAME_KEYS",
    "PRESET_DESC_KEYS",
    "PRESET_NOTES_KEYS",
    "PRESET_TEST_CASES",
    "XIAOMA_CHAPTERS",
    "XIAOMA_CHARACTERS",
    "XIAOMA_TEST_CASE_CONFIG",
    "XIAOMA_NOVEL_CONFIG",
    "REDRIDINGHOOD_CHAPTERS",
    "REDRIDINGHOOD_CHARACTERS",
    "REDRIDINGHOOD_TEST_CASE_CONFIG",
    "REDRIDINGHOOD_NOVEL_CONFIG",
    "EMPEROR_CHAPTERS",
    "EMPEROR_CHARACTERS",
    "EMPEROR_TEST_CASE_CONFIG",
    "EMPEROR_NOVEL_CONFIG",
    # LLM
    "DEFAULT_TEMPERATURE",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TIMEOUT",
    "DEFAULT_VIDEO_DURATION",
    "LOG_SYSTEM_PROMPT_MAX_LENGTH",
    "LOG_USER_PROMPT_MAX_LENGTH",
    "LOG_RESPONSE_MAX_LENGTH",
    "LOG_ERROR_MESSAGE_MAX_LENGTH",
    "NOVEL_TEXT_MAX_LENGTH",
    "CHAPTER_CONTENT_MAX_LENGTH",
    "DEFAULT_PARSE_CHARACTERS_PROMPT",
    "CHAPTER_RANGE_PLACEHOLDER",
    "DEFAULT_CHAPTER_RANGE_DESCRIPTION",
    "DEFAULT_PARSE_SCENES_PROMPT",
    "DEFAULT_VIDEO_PROMPT_EXPAND_SYSTEM",
    "DEFAULT_CHARACTER_APPEARANCE_FALLBACK",
    "DEFAULT_SCENE_SETTING_FALLBACK",
    "get_character_appearance_prompt",
    "get_scene_setting_prompt",
    # Prompt Template
    "PromptTemplateType",
    "PROMPT_TEMPLATE_TYPES",
    "PROMPT_TEMPLATE_TYPE_CONFIG",
    "get_template_type_name_key",
    "get_template_type_desc_key",
    "get_template_type_icon",
    "get_template_type_color",
]
