"""
工作流相关常量定义

包含工作流类型、默认配置等常量
翻译键直接嵌入工作流配置中，便于维护
"""

from app.constants.capability import CLIP_MAX_DURATION

# 翻译键前缀
I18N_PREFIX = "tasks"
NAME_KEY_PREFIX = f"{I18N_PREFIX}.workflowNames"
DESC_KEY_PREFIX = f"{I18N_PREFIX}.workflowDescriptions"


# 工作流类型定义
RETIRED_H3_WORKFLOW_TYPES = frozenset({
    "video", "first_last_video", "three_frame_video", "four_frame_video",
})

WORKFLOW_TYPES = {
    "character": "人设生成",
    "scene": "场景生成",
    "shot_scene": "分镜生图（场景）",
    "shot_character_scene": "分镜生图（角色+场景）",
    "shot_scene_prop": "分镜生图（场景+道具）",
    "shot": "分镜生图（角色+场景+道具）",
    "video": "单帧生视频",
    "transition": "分镜生转场视频",
    "prop": "道具生成",
    "voice_design": "音色设计",
    "audio": "音频生成",
    "background_music": "背景音乐",
    "subtitle_asr": "字幕语音识别",
    "audio_transcription": "语音转文字",
    "keyframe_image": "关键帧生图",
    "single_image_edit": "单图编辑",
    "multi_image_edit": "多图编辑",
    "first_last_video": "首尾帧生视频",
    "three_frame_video": "三帧生视频",
    "four_frame_video": "四帧生视频",
    "multi_reference_video": "多参考生视频",
    "video_upscale": "高清放大",
    "TEMPORAL_EXTEND": "时序续生成",
    "VIDEO_CONTINUATION": "视频续生成",
}


# Removed image presets may still exist in databases created by earlier releases.
# Keep their filenames here so loading the current presets also retires old rows,
# including copies whose file_path points to a previous deployment directory.
RETIRED_IMAGE_WORKFLOW_FILES = frozenset({
    "character_default.json",
    "character_single.json",
    "character_z_image_turbo_four_view.json",
    "scene_default.json",
    "prop_default.json",
    "scene_flux2_klein_20260831_api.json",
    "prop_flux2_klein_20260831_api.json",
    "shot_scene_flux2_klein_single_ref_edit.json",
    "shot_character_scene_flux2_klein_dual_ref_edit.json",
    "shot_scene_prop_flux2_klein_dual_ref_edit.json",
    "shot_flux2_klein_three_ref_edit.json",
    "shot_flux2_klein_dual_reference.json",
    "shot_flux2_klein.json",
    "keyframe_flux2_klein.json",
    "single_image_edit_flux2_klein.json",
    "shot_scene_qwen_edit_2511.json",
    "shot_character_scene_qwen_edit_2511.json",
    "shot_scene_prop_qwen_edit_2511.json",
})


# 默认工作流文件名映射（仅包含仍提供系统预设的类型）
DEFAULT_WORKFLOWS = {
    "character": "moss_image_t2i_character_four_view_v20261020.json",
    "scene": "moss_image_t2i_scene_v20261020.json",
    "prop": "moss_image_t2i_prop_v20261020.json",
    "shot_scene": "qwen_image_2_1_turbo_shot_scene_v20261018.json",
    "shot_character_scene": "qwen_image_2_1_turbo_shot_character_scene_v20261018.json",
    "shot_scene_prop": "qwen_image_2_1_turbo_shot_scene_prop_v20261018.json",
    "shot": "qwen_image_2_1_turbo_shot_v20261018.json",
    "video": "video_minimax_h3_ref2va_fast.json",
    "voice_design": "Qwen3-TTS-Voice-Design.json",  # 实际是音色设计工作流
    "audio": "Qwen3-TTS-Voice-Clone.json",  # 音频生成工作流（带参考音频的语音克隆）
    "background_music": "ace_step_background_music_v1.json",
    "keyframe_image": "qwen_image_2_1_turbo_keyframe_image_v20261018.json",
    "single_image_edit": "qwen_image_2_1_turbo_single_image_edit_v20261018.json",
    "multi_image_edit": "qwen_image_2_1_multi_image_edit_v20260926.json",
    "first_last_video": "first_last_video_minimax_h3_ref2va.json",
    "three_frame_video": "three_frame_video_minimax_h3_ref2va.json",
    "four_frame_video": "four_frame_video_minimax_h3_ref2va.json",
    "video_upscale": "video_upscale_topaz_v1_api_20260923.json",
    "TEMPORAL_EXTEND": "temporal_extend_h3_v1_20260925.json",
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
    "background_music": {
        "music_style_node_id": "14",
        "music_lyrics_node_id": "15",
        "music_duration_node_id": "98",
        "music_conditioning_node_id": "94",
        "save_audio_node_id": "13",
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
        # 帧数节点 (INTConstant)
        "frame_count_node_id": "35",
        # 时长秒数节点 (INTConstant，标题为 LENGTH (in seconds))
        "duration_seconds_node_id": "",
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
    "single_image_edit": {
        # 待编辑图片节点 (LoadImage)
        "load_image_node_id": "76",
        # 提示词节点
        "prompt_node_id": "117",
        # 保存图片节点
        "save_image_node_id": "9",
    },
    "multi_image_edit": {
        "prompt_node_id": "516",
        "save_image_node_id": "515",
        "width_node_id": "517",
        "height_node_id": "518",
        "load_image_node_1": "470",
        "load_image_node_2": "510",
        "load_image_node_3": "503",
        "load_image_node_4": "520",
        "load_image_node_5": "521",
        "load_image_node_6": "522",
        "load_image_node_7": "523",
        "load_image_node_8": "524",
        "load_image_node_9": "525",
    },
    "shot_scene": {
        "prompt_node_id": "184",
        "save_image_node_id": "163",
        "width_node_id": "182",
        "height_node_id": "183",
        "scene_reference_image_node_id": "170",
    },
    "shot_character_scene": {
        "prompt_node_id": "184",
        "save_image_node_id": "163",
        "width_node_id": "182",
        "height_node_id": "183",
        "character_reference_image_node_id": "170",
        "scene_reference_image_node_id": "171",
    },
    "shot_scene_prop": {
        "prompt_node_id": "184",
        "save_image_node_id": "163",
        "width_node_id": "182",
        "height_node_id": "183",
        "scene_reference_image_node_id": "170",
        "prop_reference_image_node_id": "171",
    },
    "first_last_video": {
        "prompt_node_id": "138",
        "first_image_node_id": "137",
        "last_image_node_id": "139",
        "video_save_node_id": "150",
        "megapixels_node_id": "171",
        "megapixels_value": "0.4",
        "frame_count_node_id": "",
        "duration_seconds_node_id": "132",
        "reference_audio_node_id": "",
    },
    "three_frame_video": {
        "prompt_node_id": "138",
        "video_save_node_id": "150",
        "reference_image_node_id": "137",
        "keyframe_node_1": "139",
        "keyframe_node_2": "172",
        "megapixels_node_id": "171",
        "megapixels_value": "0.4",
        "frame_count_node_id": "",
        "duration_seconds_node_id": "132",
        "reference_audio_node_id": "",
    },
    "four_frame_video": {
        "prompt_node_id": "138",
        "video_save_node_id": "150",
        "reference_image_node_id": "137",
        "keyframe_node_1": "139",
        "keyframe_node_2": "172",
        "keyframe_node_3": "173",
        "megapixels_node_id": "171",
        "megapixels_value": "0.4",
        "frame_count_node_id": "",
        "duration_seconds_node_id": "132",
        "reference_audio_node_id": "",
    },
    "multi_reference_video": {
        "prompt_node_id": "138",
        "video_save_node_id": "169",
        "reference_to_video_node_id": "136",
        "megapixels_node_id": "171",
        "megapixels_value": "0.4",
        "duration_seconds_node_id": "132",
        "load_image_node_1": "137",
        "load_image_node_2": "139",
        "load_image_node_3": "172",
        "load_image_node_4": "173",
        "load_image_node_5": "175",
        "load_image_node_6": "174",
        "load_image_node_7": "176",
        "load_image_node_8": "177",
        "load_image_node_9": "178",
    },
    "video_upscale": {
        "load_video_node_id": "2",
        "scale_node_id": "15",
        "scale_value": "2x",
        "video_save_node_id": "3",
    },
    "TEMPORAL_EXTEND": {
        "load_video_node_id": "66",
        "duration_seconds_node_id": "125",
        "prompt_node_id": "120",
        "reference_to_video_node_id": "55",
        "load_image_node_1": "142",
        "load_image_node_2": "141",
        "load_image_node_3": "143",
        "load_image_node_4": "137",
        "load_image_node_5": "138",
        "load_image_node_6": "140",
        "load_image_node_7": "135",
        "load_image_node_8": "136",
        "load_image_node_9": "139",
        "keyframe_node_1": "117",
        "keyframe_node_2": "128",
        "keyframe_node_3": "129",
        "keyframe_node_4": "130",
        "keyframe_node_5": "131",
        "keyframe_node_6": "132",
        "keyframe_node_7": "133",
        "keyframe_node_8": "134",
        "custom_keyframes_node_id": "116",
        "clip_video_output_node_id": "39",
        "video_save_node_id": "65",
    },
}


# 额外的系统工作流文件列表
# 注意：列表顺序决定默认激活优先级，每种类型的第一个工作流会成为默认激活
# nameKey/descriptionKey: 翻译键，前端通过此键获取多语言文本
EXTRA_SYSTEM_WORKFLOWS = [
    {
        "filename": "subtitle_asr_qwen3_v1.json",
        "type": "subtitle_asr",
        "name": "Qwen3 ASR HF 台词时间定位",
        "nameKey": f"{NAME_KEY_PREFIX}.Qwen3 ASR HF 台词时间定位",
        "description": "AILab Qwen3-ASR 1.7B-hf 与 ForcedAligner 0.6B-hf 生成字幕时间轴",
        "descriptionKey": f"{DESC_KEY_PREFIX}.AILab Qwen3-ASR 1.7B-hf 与 ForcedAligner 0.6B-hf 生成字幕时间轴",
        "node_mapping": {
            "load_audio_node_id": "12",
            "timestamps_output_node_id": "17",
            "text_list_output_node_id": "19",
            "start_times_output_node_id": "20",
            "end_times_output_node_id": "21",
        },
    },
    {
        "filename": "audio_transcription_qwen3_hf_v1.json",
        "type": "audio_transcription",
        "name": "Qwen3 ASR HF 提取声音文本",
        "nameKey": f"{NAME_KEY_PREFIX}.Qwen3 ASR HF 提取声音文本",
        "description": "AILab Qwen3-ASR 1.7B-hf 从音频提取文本，不生成时间轴",
        "descriptionKey": f"{DESC_KEY_PREFIX}.AILab Qwen3-ASR 1.7B-hf 从音频提取文本，不生成时间轴",
        "node_mapping": {
            "load_audio_node_id": "12",
            "text_output_node_id": "13",
        },
    },
] + [
    # Qwen Image 2.1 Turbo variants use the same model/sampler as the 9-image
    # edit workflow, with only the reference slots needed by each task type.
    {
        "filename": f"qwen_image_2_1_turbo_{wf_type}_v20261018.json",
        "type": wf_type,
        "name": f"Qwen Image 2.1 Turbo {label} V20261018",
        "nameKey": f"{NAME_KEY_PREFIX}.Qwen Image 2.1 Turbo {label} V20261018",
        "description": f"Qwen Image 2.1 Turbo {label}，{reference_description}",
        "descriptionKey": f"{DESC_KEY_PREFIX}.Qwen Image 2.1 Turbo {label}，{reference_description}",
        "node_mapping": {
            "prompt_node_id": "516",
            "save_image_node_id": "515",
            "width_node_id": "517",
            "height_node_id": "518",
            **reference_mapping,
        },
    }
    for wf_type, label, reference_description, reference_mapping in [
        ("shot_scene", "分镜生图（场景）", "使用场景参考图", {"scene_reference_image_node_id": "470"}),
        ("shot_character_scene", "分镜生图（角色+场景）", "依次使用角色、场景参考图", {"character_reference_image_node_id": "470", "scene_reference_image_node_id": "510"}),
        ("shot_scene_prop", "分镜生图（场景+道具）", "依次使用场景、道具参考图", {"scene_reference_image_node_id": "470", "prop_reference_image_node_id": "510"}),
        ("shot", "分镜生图（角色+场景+道具）", "依次使用角色、场景、道具参考图", {"character_reference_image_node_id": "470", "scene_reference_image_node_id": "510", "prop_reference_image_node_id": "503"}),
        ("keyframe_image", "关键帧生图", "使用单张关键帧参考图", {"reference_image_node_id": "470"}),
        ("single_image_edit", "单图编辑", "使用单张原图", {"load_image_node_id": "470"}),
    ]
] + [
    {
        "filename": "ace_step_background_music_v1.json",
        "type": "background_music",
        "name": "ACE-Step1.5 纯器乐背景音乐 V1",
        "nameKey": f"{NAME_KEY_PREFIX}.ACE-Step1.5 纯器乐背景音乐 V1",
        "description": "ACE-Step1.5 纯器乐生成；风格、旋律与时长按配乐规划动态设置，成品须人工听检",
        "descriptionKey": f"{DESC_KEY_PREFIX}.ACE-Step1.5 纯器乐生成；风格、旋律与时长按配乐规划动态设置，成品须人工听检",
        "node_mapping": DEFAULT_WORKFLOW_NODE_MAPPINGS["background_music"],
    },
    {
        "filename": "multi_reference_video_minimax_h3_ref2va_20260928.json",
        "type": "multi_reference_video",
        "name": "Minimax H3 多参考生视频 V20260928",
        "nameKey": f"{NAME_KEY_PREFIX}.Minimax H3 多参考生视频 V20260928",
        "description": "MiniMax H3 多参考生视频，支持 0～9 张参考图",
        "descriptionKey": f"{DESC_KEY_PREFIX}.MiniMax H3 多参考生视频，支持 0～9 张参考图",
        "node_mapping": DEFAULT_WORKFLOW_NODE_MAPPINGS["multi_reference_video"],
        "extension": {"max_clip_duration": CLIP_MAX_DURATION, "min_reference_images": 0, "max_reference_images": 9},
    },
    {
        "filename": "temporal_extend_h3_v1_20260925.json",
        "type": "TEMPORAL_EXTEND",
        "name": "NovelFlow H3 AV 时序续生成 V1",
        "nameKey": f"{NAME_KEY_PREFIX}.NovelFlow H3 AV 时序续生成 V1",
        "description": "基于已有视频进行连续生成，可选使用 1～8 张时间锚点关键帧控制指定时刻的视觉状态。",
        "descriptionKey": f"{DESC_KEY_PREFIX}.基于已有视频进行连续生成，可选使用 1～8 张时间锚点关键帧控制指定时刻的视觉状态。",
        "node_mapping": DEFAULT_WORKFLOW_NODE_MAPPINGS["TEMPORAL_EXTEND"],
        "extension": {"workflow_capability": "TEMPORAL_EXTEND"},
    },
    {
        "filename": "video_continuation_h3_av_extend_minimal_v1_20260925.json",
        "type": "VIDEO_CONTINUATION",
        "name": "NovelFlow H3 AV 视频续生成 Minimal V1",
        "nameKey": f"{NAME_KEY_PREFIX}.NovelFlow H3 AV 视频续生成 Minimal V1",
        "description": "基于已有视频连续生成，支持提示词控制并具备 TEMPORAL_EXTEND 能力。",
        "descriptionKey": f"{DESC_KEY_PREFIX}.基于已有视频连续生成，支持提示词控制并具备 TEMPORAL_EXTEND 能力。",
        "node_mapping": {
            "load_video_node_id": "66",
            "duration_seconds_node_id": "105",
            "prompt_node_id": "107",
            "clip_video_output_node_id": "39",
            "video_save_node_id": "65",
            "reference_to_video_node_id": "55",
            "load_image_node_1": "69",
            "load_image_node_2": "68",
            "load_image_node_3": "109",
            "load_image_node_4": "110",
            "load_image_node_5": "111",
            "load_image_node_6": "112",
            "load_image_node_7": "113",
            "load_image_node_8": "114",
            "load_image_node_9": "115",
        },
        "extension": {"workflow_capability": "TEMPORAL_EXTEND"},
    },
    {
        "filename": "video_upscale_topaz_v1_api_20260923.json",
        "type": "video_upscale",
        "name": "Topaz Video 星光放大 V1",
        "nameKey": f"{NAME_KEY_PREFIX}.Topaz Video 星光放大 V1",
        "description": "Topaz Video 高清放大工作流，支持 2x、4x、8x",
        "descriptionKey": f"{DESC_KEY_PREFIX}.Topaz Video 高清放大工作流，支持 2x、4x、8x",
        "node_mapping": DEFAULT_WORKFLOW_NODE_MAPPINGS["video_upscale"],
    },
    {
        "filename": "video_minimax_h3_ref2va_fast.json",
        "type": "video",
        "name": "Minimax+H3+ref2va加速工作流",
        "nameKey": f"{NAME_KEY_PREFIX}.Minimax+H3+ref2va加速工作流",
        "description": "MiniMax H3 单帧参考视频加速工作流",
        "descriptionKey": f"{DESC_KEY_PREFIX}.MiniMax H3 单帧参考视频加速工作流",
        "node_mapping": {"prompt_node_id": "138", "video_save_node_id": "150", "max_side_node_id": None, "megapixels_node_id": "170", "megapixels_value": "0.4", "reference_image_node_id": "137", "frame_count_node_id": None, "reference_audio_node_id": None, "duration_seconds_node_id": "132"},
    },
    {
        "filename": "first_last_video_minimax_h3_ref2va.json",
        "type": "first_last_video",
        "name": "Minimax H3 首尾帧生视频",
        "nameKey": f"{NAME_KEY_PREFIX}.Minimax H3 首尾帧生视频",
        "description": "MiniMax H3 首尾帧参考视频工作流，使用 START/END 两张图",
        "descriptionKey": f"{DESC_KEY_PREFIX}.MiniMax H3 首尾帧参考视频工作流，使用 START/END 两张图",
        "node_mapping": DEFAULT_WORKFLOW_NODE_MAPPINGS["first_last_video"],
        "extension": {"max_clip_duration": CLIP_MAX_DURATION, "frame_count": 2},
    },
    {
        "filename": "three_frame_video_minimax_h3_ref2va.json",
        "type": "three_frame_video",
        "name": "Minimax H3 三帧生视频",
        "nameKey": f"{NAME_KEY_PREFIX}.Minimax H3 三帧生视频",
        "description": "MiniMax H3 三帧参考视频工作流，使用 3 张关键帧图",
        "descriptionKey": f"{DESC_KEY_PREFIX}.MiniMax H3 三帧参考视频工作流，使用 3 张关键帧图",
        "node_mapping": DEFAULT_WORKFLOW_NODE_MAPPINGS["three_frame_video"],
        "extension": {"max_clip_duration": CLIP_MAX_DURATION, "frame_count": 3},
    },
    {
        "filename": "four_frame_video_minimax_h3_ref2va.json",
        "type": "four_frame_video",
        "name": "Minimax H3 四帧生视频",
        "nameKey": f"{NAME_KEY_PREFIX}.Minimax H3 四帧生视频",
        "description": "MiniMax H3 四帧参考视频工作流，使用 4 张关键帧图",
        "descriptionKey": f"{DESC_KEY_PREFIX}.MiniMax H3 四帧参考视频工作流，使用 4 张关键帧图",
        "node_mapping": DEFAULT_WORKFLOW_NODE_MAPPINGS["four_frame_video"],
        "extension": {"max_clip_duration": CLIP_MAX_DURATION, "frame_count": 4},
    },
    {
        "filename": "transition_ltx2_camera.json",
        "type": "transition",
        "name": "LTX2 镜头转场视频",
        "nameKey": f"{NAME_KEY_PREFIX}.LTX2 镜头转场视频",
        "description": "适合：首尾帧是同一场景不同景别/角度",
        "descriptionKey": f"{DESC_KEY_PREFIX}.适合：首尾帧是同一场景不同景别/角度",
        "node_mapping": {"first_image_node_id": "98", "last_image_node_id": "106", "frame_count_node_id": "174", "duration_seconds_node_id": "", "megapixels_node_id": "", "megapixels_value": "0.4", "video_save_node_id": "105"},
    },
    {
        "filename": "transition_ltx2_lighting.json",
        "type": "transition",
        "name": "LTX2 光线转场视频",
        "nameKey": f"{NAME_KEY_PREFIX}.LTX2 光线转场视频",
        "description": "适合：首尾帧颜色差很多，但场景/人物不变",
        "descriptionKey": f"{DESC_KEY_PREFIX}.适合：首尾帧颜色差很多，但场景/人物不变",
        "node_mapping": {"first_image_node_id": "98", "last_image_node_id": "106", "frame_count_node_id": "174", "duration_seconds_node_id": "", "megapixels_node_id": "", "megapixels_value": "0.4", "video_save_node_id": "105"},
    },
    {
        "filename": "transition_ltx2_first_last_frame.json",
        "type": "transition",
        "name": "LTX2 遮挡转场视频",
        "nameKey": f"{NAME_KEY_PREFIX}.LTX2 遮挡转场视频",
        "description": "适合：两张图差异大，想自然衔接",
        "descriptionKey": f"{DESC_KEY_PREFIX}.适合：两张图差异大，想自然衔接",
        "node_mapping": {"first_image_node_id": "98", "last_image_node_id": "106", "frame_count_node_id": "174", "duration_seconds_node_id": "", "megapixels_node_id": "", "megapixels_value": "0.4", "video_save_node_id": "105"},
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
    {
        "filename": "qwen_image_2_1_multi_image_edit_v20260926.json",
        "type": "multi_image_edit",
        "name": "Qwen image 2.1图片编辑 (任意数量参考图) API V20260926.json",
        "nameKey": f"{NAME_KEY_PREFIX}.Qwen image 2.1图片编辑 (任意数量参考图) API V20260926.json",
        "description": "任意数目参考图编辑",
        "descriptionKey": f"{DESC_KEY_PREFIX}.任意数目参考图编辑",
        "node_mapping": DEFAULT_WORKFLOW_NODE_MAPPINGS["multi_image_edit"],
    },
]


def _promoted_workflow(filename, legacy_user_filename, wf_type, name, node_mapping, extension=None):
    """Register a selected user workflow without changing its graph or display text."""
    config = {
        "filename": filename,
        "legacy_user_filename": legacy_user_filename,
        "type": wf_type,
        "name": name,
        "nameKey": f"{NAME_KEY_PREFIX}.{name}",
        "description": name,
        "descriptionKey": f"{DESC_KEY_PREFIX}.{name}",
        "node_mapping": node_mapping,
    }
    if extension is not None:
        config["extension"] = extension
    return config


_QWEN_PE_IMAGE_MAPPING = {
    "prompt_node_id": "516",
    "save_image_node_id": "515",
    "width_node_id": "517",
    "height_node_id": "518",
}

EXTRA_SYSTEM_WORKFLOWS.extend([
    _promoted_workflow(
        "moss_image_t2i_character_four_view_v20261020.json",
        "moss_image_t2i四视图APIV20261020_character.json",
        "character", "moss_image_t2i【四视图】API V20261020",
        {"appearance_node_id": "27", "style_node_id": "26", "save_image_node_id": "9"},
    ),
    _promoted_workflow(
        "moss_image_t2i_scene_v20261020.json",
        "image_moss_image_t2i场景and道具APIV20261020_scene.json",
        "scene", "image_moss_image_t2i（场景）API V20261020",
        {"prompt_node_id": "25", "save_image_node_id": "9"},
    ),
    _promoted_workflow(
        "moss_image_t2i_prop_v20261020.json",
        "image_moss_image_t2i道具APIV20261020_prop.json",
        "prop", "image_moss_image_t2i（道具）API V20261020",
        {"prompt_node_id": "25", "save_image_node_id": "9"},
    ),
    _promoted_workflow(
        "qwen_image_2_1_pe_shot_scene_v20290922.json",
        "Qwenimage21图片编辑场景PEAPIV20290922_shot_scene.json",
        "shot_scene", "Qwen image 2.1图片编辑 (场景) PE API V20290922",
        {**_QWEN_PE_IMAGE_MAPPING, "scene_reference_image_node_id": "470"},
    ),
    _promoted_workflow(
        "qwen_image_2_1_pe_shot_character_scene_v20260922.json",
        "Qwenimage21图片编辑角色场景PEAPIV20260922_shot_character_scene.json",
        "shot_character_scene", "Qwen image 2.1图片编辑 (角色+场景) PE API V20260922",
        {**_QWEN_PE_IMAGE_MAPPING, "character_reference_image_node_id": "470", "scene_reference_image_node_id": "510"},
    ),
    _promoted_workflow(
        "qwen_image_2_1_pe_shot_scene_prop_v20260922.json",
        "Qwenimage21图片编辑场景道具PEAPIV20260922_shot_scene_prop.json",
        "shot_scene_prop", "Qwen image 2.1图片编辑 (场景+道具) PE API V20260922",
        {**_QWEN_PE_IMAGE_MAPPING, "scene_reference_image_node_id": "470", "prop_reference_image_node_id": "510"},
    ),
    _promoted_workflow(
        "qwen_image_2_1_pe_shot_v20260922.json",
        "Qwenimage21图片编辑角色场景道具PEAPIV20260922_shot.json",
        "shot", "Qwen image 2.1图片编辑 (角色+场景+道具) PE API V20260922",
        {**_QWEN_PE_IMAGE_MAPPING, "character_reference_image_node_id": "470", "scene_reference_image_node_id": "510", "custom_reference_image_node_1": "503"},
    ),
    _promoted_workflow(
        "qwen_image_2_1_pe_single_image_edit_v20260922.json",
        "Qwenimage21图片编辑单图编辑PEAPIV20260922_single_image_edit.json",
        "single_image_edit", "Qwen image 2.1图片编辑 (单图编辑) PE API V20260922",
        {"load_image_node_id": "470", "prompt_node_id": "516", "save_image_node_id": "515"},
    ),
    _promoted_workflow(
        "h3_multi_reference_2pass_3d_upscaler_v20261021.json",
        "NovelFlow_H3_Ref2VA_2Pass_3D_Upscaler_V1APIV20261021_multi_reference_video_1.json",
        "multi_reference_video", "NovelFlow_H3_Ref2VA_2Pass_3D_Upscaler_V1 API V20261021",
        {
            **DEFAULT_WORKFLOW_NODE_MAPPINGS["multi_reference_video"],
            "video_save_node_id": "197", "duration_seconds_node_id": "219",
            "megapixels_value": "0.52", "max_side_node_id": None, "frame_count_node_id": None,
            "second_pass_upscale_step_node_id": "221", "second_pass_upscale_step": "2",
            "second_pass_upscale_scale_node_id": "230", "second_pass_upscale_scale": "2",
        },
        {"max_clip_duration": CLIP_MAX_DURATION, "min_reference_images": 0, "max_reference_images": 9},
    ),
    _promoted_workflow(
        "h3_video_continuation_2pass_3d_upscaler_v20261021.json",
        "NovelFlow_H3_AV_Extend_Minimal_2Pass_3D_Upscaler_V1APIV20261021_VIDEO_CONTINUATION_1.json",
        "VIDEO_CONTINUATION", "NovelFlow_H3_AV_Extend_Minimal_2Pass_3D_Upscaler_V1 API V20261021",
        {
            "load_video_node_id": "66", "duration_seconds_node_id": "105",
            "prompt_node_id": "107", "megapixels_node_id": "145", "megapixels_value": "0.52",
            "video_save_node_id": "65", "clip_video_output_node_id": "143",
            "reference_to_video_node_id": "55",
            "second_pass_upscale_step_node_id": "118", "second_pass_upscale_step": "2",
            "second_pass_upscale_scale_node_id": "119", "second_pass_upscale_scale": "2",
            **{f"load_image_node_{index}": node_id for index, node_id in enumerate(
                ("69", "68", "109", "110", "111", "112", "113", "114", "115"), 1)},
        },
        {"workflow_capability": "TEMPORAL_EXTEND"},
    ),
    _promoted_workflow(
        "h3_temporal_extend_2pass_3d_upscaler_v20261021.json",
        "NovelFlow_H3_AV_Extend_TemporalAnchor_Test_2Pass_3D_Upscaler_V1APIV20261021_TEMPORAL_EXTEND.json",
        "TEMPORAL_EXTEND", "NovelFlow_H3_AV_Extend_TemporalAnchor_Test_2Pass_3D_Upscaler_V1 API V20261021",
        {
            **DEFAULT_WORKFLOW_NODE_MAPPINGS["TEMPORAL_EXTEND"],
            "megapixels_node_id": "169", "megapixels_value": "0.52",
            "custom_keyframes_node_id": "116", "custom_keyframes_node_ids": ["116", "151"],
            "clip_video_output_node_id": "168",
            "second_pass_upscale_step_node_id": "144", "second_pass_upscale_step": "2",
            "second_pass_upscale_scale_node_id": "145", "second_pass_upscale_scale": "2",
        },
        {"workflow_capability": "TEMPORAL_EXTEND"},
    ),
])


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
