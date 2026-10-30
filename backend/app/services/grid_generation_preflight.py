"""Grid-only batch validation catalog and the two runtime review controls."""

import json


CHECKS = (
    {"id": "GRID_CHAPTER_INPUT", "stage": "before_queue", "label": "章回输入与覆盖保护",
     "description": "正文必须存在；已有 Shot 的章回不能被批量解析覆盖。", "configurable": False},
    {"id": "GRID_TASK_OWNERSHIP", "stage": "before_queue", "label": "任务归属与并发",
     "description": "核对小说、章回、Shot 归属，防止同章重复提交和旧任务回写。", "configurable": False},
    {"id": "GRID_SHOT_PLAN_CONTRACT", "stage": "planning", "label": "叙事 Shot 与台词",
     "description": "核对 Shot 数量、时长、资源、说话人和画外声必需字段。不同情绪的声音描述允许变化。", "configurable": False},
    {"id": "GRID_PANEL_PLAN_CONTRACT", "stage": "planning", "label": "宫格与台词分配",
     "description": "格数和编号必须匹配版式；台词按原顺序恰好分配一次；画外台词所在格无人出镜。", "configurable": False},
    {"id": "GRID_IMAGE_INPUT_OUTPUT", "stage": "image", "label": "生图输入与图片文件",
     "description": "工作流、参考素材和图片必须有效；整板比例与子格 16:9 必须正确。", "configurable": False},
    {"id": "GRID_PANEL_AI_REVIEW", "stage": "image", "label": "自动逐格 AI 初审",
     "description": "用于批量生图和自动生视频。关闭后普通 pending 子格不自动审查；画外声子格和单独提交的“批量 AI 审图”仍会审查。已有 FAIL 始终阻断。",
     "configurable": True},
    {"id": "GRID_PANEL_FAIL_RETRY", "stage": "image", "label": "初审 FAIL 自动重做一次",
     "description": "开启后仅对 FAIL 子格自动重做一次并重新初审；关闭后直接停在该 Shot，其他 Shot 继续。",
     "configurable": True},
    {"id": "GRID_PANEL_NON_FAIL", "stage": "video", "label": "子格进入 Clip 的条件",
     "description": "有图片且状态不是 FAIL 即可继续；PASS、WARNING、PENDING 都可进入 Clip。", "configurable": False},
    {"id": "GRID_CLIP_PLAN_CONTRACT", "stage": "video", "label": "Clip 时间轴与台词",
     "description": "Clip 必须完整、按顺序覆盖 Shot 时长、宫格和原文台词。", "configurable": False},
    {"id": "GRID_H3_INPUT_BINDING", "stage": "video", "label": "H3 提示词与参考图",
     "description": "核对原文对白、Subject/Speaker、图片引用、工作流节点及输入版本。", "configurable": False},
    {"id": "GRID_OFFSCREEN_AUDIO", "stage": "assembly", "label": "画外声音轨与画面",
     "description": "核对画外台词音轨与原文；使用无人出镜的环境子格生成动态视频。", "configurable": False},
    {"id": "GRID_VIDEO_ARTIFACT", "stage": "assembly", "label": "视频文件与合并来源",
     "description": "Clip 和 Shot 文件必须存在，且片段顺序和来源有效。", "configurable": False},
)

DEFAULT_POLICY = {"GRID_PANEL_AI_REVIEW": True, "GRID_PANEL_FAIL_RETRY": True}


def normalize_policy(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_POLICY) or any(type(item) is not bool for item in value.values()):
        raise ValueError("宫格批量预检策略只接受已列出的可选项目及布尔值")
    return {**DEFAULT_POLICY, **value}


def config_policy(config):
    try:
        return normalize_policy(json.loads(config.grid_generation_quality_policy or "{}")) if config else normalize_policy({})
    except (TypeError, ValueError):
        return normalize_policy({})


def catalog(policy=None):
    policy = normalize_policy(policy or {})
    return [{**check, "enabled": policy[check["id"]] if check["configurable"] else True}
            for check in CHECKS]
