"""The stable, business-independent notification event registry."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class NotificationEvent:
    event_code: str
    name: str
    category: str
    description: str
    enabled: bool = True


_EVENTS = (
    ("shot.planning.completed", "Shot 规划完成", "Shot 规划", "Shot 规划已完成"),
    ("shot.planning.failed", "Shot 规划失败", "Shot 规划", "Shot 规划未能完成"),
    ("visual_state.generation.completed", "视觉状态图片生成完成", "视觉状态", "关键帧图片任务已完成；不代表视觉状态规划"),
    ("visual_state.generation.failed", "视觉状态图片生成失败", "视觉状态", "关键帧图片任务最终失败"),
    ("clip.prompt.build.completed", "Clip 提示词构建完成", "Clip 提示词", "Clip 提示词构建已完成"),
    ("clip.prompt.build.failed", "Clip 提示词构建失败", "Clip 提示词", "Clip 提示词构建未能完成"),
    ("clip.prompt.optimize.completed", "H3 提示词优化完成", "Clip 提示词", "#14 最终优化及 Preflight 结果已保存"),
    ("clip.prompt.optimize.failed", "H3 提示词优化失败", "Clip 提示词", "#14 最终优化失败结果已保存"),
    ("preflight.repair.completed", "Preflight 修复完成", "Preflight", "Preflight 自动修复已完成"),
    ("preflight.repair.failed", "Preflight 修复失败", "Preflight", "Preflight 自动修复未能完成"),
    ("clip.generation.completed", "Clip 生成完成", "Clip 生成", "Clip 视频生成已完成"),
    ("clip.generation.failed", "Clip 生成失败", "Clip 生成", "Clip 视频生成未能完成"),
    ("clip.regeneration.completed", "Clip 重新生成完成", "Clip 生成", "Clip 视频重新生成已完成"),
    ("shot.assembly.completed", "Shot 合并完成", "Shot 合并", "Shot 素材合并已完成"),
    ("shot.assembly.failed", "Shot 合并失败", "Shot 合并", "Shot 素材合并未能完成"),
    ("shot.generation.completed", "Shot 生成完成", "Shot 生成", "Shot 生成已完成"),
    ("shot.generation.failed", "Shot 生成失败", "Shot 生成", "Shot 生成未能完成"),
    ("batch.generation.completed", "批量生成完成", "批量生成", "批量生成已完成"),
    ("batch.generation.failed", "批量生成失败", "批量生成", "批量生成未能完成"),
    ("task.review.required", "任务需要审核", "任务", "任务需要人工审核"),
    ("comfyui.connection.failed", "ComfyUI 连接失败", "系统", "ComfyUI 连接不可用"),
)

EVENT_REGISTRY = {code: NotificationEvent(code, name, category, description) for code, name, category, description in _EVENTS}
for code, name, category, description, enabled in (
    ("image.review.passed", "AI 评审通过", "图片质量评审", "图片质量评审 PASS，不改变图片生成状态", False),
    ("image.review.failed", "AI 评审不通过", "图片质量评审", "图片质量评审 FAIL 或 REVIEW；不自动重绘", True),
    ("image.review.error", "AI 评审异常", "图片质量评审", "无法取得有效评审结果；原图片仍然保留", True),
    ("image.generation.completed", "图片生成完成", "图片生成", "角色、场景、道具或主分镜等图片任务完成（关键帧使用视觉状态事件）", False),
    ("image.generation.failed", "图片生成失败", "图片生成", "非关键帧图片任务最终失败", True),
):
    EVENT_REGISTRY[code] = NotificationEvent(code, name, category, description, enabled)


def list_events(switches: dict[str, bool]) -> list[dict]:
    return [{**asdict(event), "enabled": switches.get(code, event.enabled)} for code, event in EVENT_REGISTRY.items()]
