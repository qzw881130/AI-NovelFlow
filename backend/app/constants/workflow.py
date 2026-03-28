"""
工作流相关常量定义

包含工作流类型、默认配置等常量
翻译键直接嵌入工作流配置中，便于维护
"""

# 翻译键前缀
I18N_PREFIX = "tasks"
NAME_KEY_PREFIX = f"{I18N_PREFIX}.workflowNames"
DESC_KEY_PREFIX = f"{I18N_PREFIX}.workflowDescriptions"


# 工作流类型定义
WORKFLOW_TYPES = {
    "character": "人设生成",
    "scene": "场景生成",
    "shot": "分镜生图",
    "video": "分镜生视频",
    "transition": "分镜生转场视频",
    "prop": "道具生成",
    "voice_design": "音色设计",
    "audio": "音频生成",
    "keyframe_image": "关键帧生图"
}


# 默认工作流文件名映射 (每个类型的默认工作流)
DEFAULT_WORKFLOWS = {
    "character": "character_default.json",
    "scene": "scene_default.json",
    "shot": "shot_default.json",
    "video": "video_default.json",
    "prop": "prop_default.json",
    "voice_design": "Qwen3-TTS-Voice-Design.json",  # 实际是音色设计工作流
    "audio": "Qwen3-TTS-Voice-Clone.json",  # 音频生成工作流（带参考音频的语音克隆）
    "keyframe_image": "keyframe_flux2_klein.json"
}


# 默认工作流的节点映射配置
# 用于指定工作流中各功能节点的ID，便于动态替换参数
# 注意：CR Prompt Text 节点使用 prompt 字段存储文本内容
DEFAULT_WORKFLOW_NODE_MAPPINGS = {
    "voice_design": {
        # 音色提示词节点 (CR Prompt Text 节点，prompt 字段 -> instruct)
        "voice_prompt_node_id": "53",
        # 参考文本节点 (CR Prompt Text 节点，prompt 字段 -> text)
        "ref_text_node_id": "54",
        # 保存音频节点 (SaveAudio)
        "save_audio_node_id": "52",
    },
    "audio": {
        # 参考音频节点 (LoadAudio)
        "reference_audio_node_id": "19",
        # 生成文本节点 (CR Prompt Text 节点，prompt 字段 -> text)
        "text_node_id": "32",
        # 情感提示词节点 (CR Prompt Text 节点，prompt 字段 -> ref_text)
        "emotion_prompt_node_id": "33",
        # 保存音频节点 (PreviewAudio，此工作流无 SaveAudio)
        "save_audio_node_id": "30",
    },
    "video": {
        # 提示词节点
        "prompt_node_id": "11",
        # 视频保存节点
        "video_save_node_id": "1",
        # 参考图片节点 (LoadImage)
        "reference_image_node_id": "12",
        # 最大边长节点
        "max_side_node_id": "36",
        # 帧数节点
        "frame_count_node_id": "35",
        # 参考音频节点 (LoadAudio) - 用于口型同步
        "reference_audio_node_id": "",
    },
    "keyframe_image": {
        # 提示词节点
        "prompt_node_id": "110",
        # 保存图片节点
        "save_image_node_id": "9",
        # 参考图片节点 (LoadImage) - 用于关键帧图片生成的参考图
        "reference_image_node_id": "76",
    },
}


# 额外的系统工作流文件列表
# 注意：列表顺序决定默认激活优先级，每种类型的第一个工作流会成为默认激活
# nameKey/descriptionKey: 翻译键，前端通过此键获取多语言文本
EXTRA_SYSTEM_WORKFLOWS = [
    {
        "filename": "character_single.json",
        "type": "character",
        "name": "Z-image-turbo 单图生成",
        "nameKey": f"{NAME_KEY_PREFIX}.Z-image-turbo 单图生成",
        "description": "Z-image-turbo【非三视图】",
        "descriptionKey": f"{DESC_KEY_PREFIX}.Z-image-turbo【非三视图】",
    },
    # 双图参考工作流（角色图+场景图）作为分镜生图的默认工作流
    {
        "filename": "shot_flux2_klein_dual_reference.json",
        "type": "shot",
        "name": "Flux2-Klein-9B 分镜生图双图参考",
        "nameKey": f"{NAME_KEY_PREFIX}.Flux2-Klein-9B 分镜生图双图参考",
        "description": "Flux2-Klein-9B 双图参考工作流，支持角色参考图+场景参考图，保持场景一致性",
        "descriptionKey": f"{DESC_KEY_PREFIX}.Flux2-Klein-9B 双图参考工作流，支持角色参考图+场景参考图，保持场景一致性",
        "node_mapping": {"prompt_node_id": "110", "save_image_node_id": "9", "width_node_id": "123", "height_node_id": "125", "character_reference_image_node_id": "76", "scene_reference_image_node_id": "128"},
    },
    {
        "filename": "shot_flux2_klein.json",
        "type": "shot",
        "name": "Flux2-Klein-9B 分镜生图",
        "nameKey": f"{NAME_KEY_PREFIX}.Flux2-Klein-9B 分镜生图",
        "description": "Flux2-Klein-9B 图像编辑工作流，仅支持角色参考图",
        "descriptionKey": f"{DESC_KEY_PREFIX}.Flux2-Klein-9B 图像编辑工作流，仅支持角色参考图",
    },
    {
        "filename": "video_ltx2_direct.json",
        "type": "video",
        "name": "LTX2 视频生成-直接版",
        "nameKey": f"{NAME_KEY_PREFIX}.LTX2 视频生成-直接版",
        "description": "LTX-2 图生视频，直接使用用户提示词",
        "descriptionKey": f"{DESC_KEY_PREFIX}.LTX-2 图生视频，直接使用用户提示词",
        "node_mapping": {"prompt_node_id": "11", "video_save_node_id": "1", "reference_image_node_id": "12", "max_side_node_id": "36", "frame_count_node_id": "35"},
    },
    {
        "filename": "video_ltx2_expanded.json",
        "type": "video",
        "name": "LTX2 视频生成-扩写版",
        "nameKey": f"{NAME_KEY_PREFIX}.LTX2 视频生成-扩写版",
        "description": "LTX-2 图生视频，使用 Qwen3 自动扩写提示词",
        "descriptionKey": f"{DESC_KEY_PREFIX}.LTX-2 图生视频，使用 Qwen3 自动扩写提示词",
        "node_mapping": {"prompt_node_id": "15", "video_save_node_id": "1", "reference_image_node_id": "12", "max_side_node_id": "36", "frame_count_node_id": "35"},
    },
    {
        "filename": "transition_ltx2_camera.json",
        "type": "transition",
        "name": "LTX2 镜头转场视频",
        "nameKey": f"{NAME_KEY_PREFIX}.LTX2 镜头转场视频",
        "description": "适合：首尾帧是同一场景不同景别/角度",
        "descriptionKey": f"{DESC_KEY_PREFIX}.适合：首尾帧是同一场景不同景别/角度",
        "node_mapping": {"first_image_node_id": "98", "last_image_node_id": "106", "frame_count_node_id": "174", "video_save_node_id": "105"},
    },
    {
        "filename": "transition_ltx2_lighting.json",
        "type": "transition",
        "name": "LTX2 光线转场视频",
        "nameKey": f"{NAME_KEY_PREFIX}.LTX2 光线转场视频",
        "description": "适合：首尾帧颜色差很多，但场景/人物不变",
        "descriptionKey": f"{DESC_KEY_PREFIX}.适合：首尾帧颜色差很多，但场景/人物不变",
        "node_mapping": {"first_image_node_id": "98", "last_image_node_id": "106", "frame_count_node_id": "174", "video_save_node_id": "105"},
    },
    {
        "filename": "transition_ltx2_first_last_frame.json",
        "type": "transition",
        "name": "LTX2 遮挡转场视频",
        "nameKey": f"{NAME_KEY_PREFIX}.LTX2 遮挡转场视频",
        "description": "适合：两张图差异大，想自然衔接",
        "descriptionKey": f"{DESC_KEY_PREFIX}.适合：两张图差异大，想自然衔接",
        "node_mapping": {"first_image_node_id": "98", "last_image_node_id": "106", "frame_count_node_id": "174", "video_save_node_id": "105"},
    },
    {
        "filename": "scene_default.json",
        "type": "scene",
        "name": "Z-image-turbo 场景生成",
        "nameKey": f"{NAME_KEY_PREFIX}.Z-image-turbo 场景生成",
        "description": "Z-image-turbo 场景生成工作流",
        "descriptionKey": f"{DESC_KEY_PREFIX}.Z-image-turbo 场景生成工作流",
        "node_mapping": {"prompt_node_id": "133", "save_image_node_id": "9"},
    },
    {
        "filename": "prop_default.json",
        "type": "prop",
        "name": "Z-image-turbo 道具生成",
        "nameKey": f"{NAME_KEY_PREFIX}.Z-image-turbo 道具生成",
        "description": "Z-image-turbo 道具生成工作流",
        "descriptionKey": f"{DESC_KEY_PREFIX}.Z-image-turbo 道具生成工作流",
        "node_mapping": {"prompt_node_id": "133", "save_image_node_id": "9"},
    },
    # 音色设计工作流（基于文本提示词设计音色）
    {
        "filename": "Qwen3-TTS-Voice-Design.json",
        "type": "voice_design",
        "name": "系统默认-音色设计",
        "nameKey": f"{NAME_KEY_PREFIX}.系统默认-音色设计",
        "description": "基于文本提示词设计音色，生成语音",
        "descriptionKey": f"{DESC_KEY_PREFIX}.基于文本提示词设计音色，生成语音",
        "node_mapping": {
            "voice_prompt_node_id": "53",
            "ref_text_node_id": "54",
            "save_audio_node_id": "52"
        },
    },
    # 音频生成工作流（带参考音频的语音克隆）
    {
        "filename": "Qwen3-TTS-Voice-Clone.json",
        "type": "audio",
        "name": "系统默认-音频生成",
        "nameKey": f"{NAME_KEY_PREFIX}.系统默认-音频生成",
        "description": "基于参考音频生成语音，支持情感提示词控制",
        "descriptionKey": f"{DESC_KEY_PREFIX}.基于参考音频生成语音，支持情感提示词控制",
        "node_mapping": {
            "reference_audio_node_id": "19",
            "text_node_id": "32",
            "emotion_prompt_node_id": "33",
            "save_audio_node_id": "30"
        },
    },
    # 关键帧图片生成工作流（基于分镜图单图参考）
    {
        "filename": "keyframe_flux2_klein.json",
        "type": "keyframe_image",
        "name": "Flux2-Klein-9B 关键帧生图",
        "nameKey": f"{NAME_KEY_PREFIX}.Flux2-Klein-9B 关键帧生图",
        "description": "Flux2-Klein-9B 关键帧生图工作流，支持参考图",
        "descriptionKey": f"{DESC_KEY_PREFIX}.Flux2-Klein-9B 关键帧生图工作流，支持参考图",
        "node_mapping": {"prompt_node_id": "110", "save_image_node_id": "9", "reference_image_node_id": "76"},
    },
]


# ==================== 辅助函数 ====================

def get_workflow_name_key(name: str) -> str:
    """获取工作流名称翻译键"""
    return f"{NAME_KEY_PREFIX}.{name}"


def get_workflow_desc_key(description: str) -> str:
    """获取工作流描述翻译键"""
    return f"{DESC_KEY_PREFIX}.{description}"


def find_workflow_config_by_name(name: str) -> dict | None:
    """根据名称查找工作流配置"""
    for wf in EXTRA_SYSTEM_WORKFLOWS:
        if wf.get("name") == name:
            return wf
    return None


def get_workflow_i18n_keys(name: str, description: str = None) -> dict:
    """
    获取工作流的翻译键
    
    优先从配置中查找，找不到则生成默认键
    
    Args:
        name: 工作流名称
        description: 工作流描述（可选）
        
    Returns:
        {"nameKey": str, "descriptionKey": str | None}
    """
    config = find_workflow_config_by_name(name)
    
    if config:
        return {
            "nameKey": config.get("nameKey"),
            "descriptionKey": config.get("descriptionKey") if description else None,
        }
    
    # 非配置中的工作流，生成默认键
    result = {"nameKey": get_workflow_name_key(name)}
    if description:
        result["descriptionKey"] = get_workflow_desc_key(description)
    return result
