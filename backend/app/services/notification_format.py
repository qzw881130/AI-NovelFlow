"""Business-facing notification text. This is a view of events, never an event schema."""
import json
import math
import re
from datetime import datetime
from datetime import timezone

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.services.notification_registry import EVENT_REGISTRY


LABELS = {
    "shot.planning.completed": "规划完成", "shot.planning.failed": "规划失败",
    "visual_state.generation.completed": "视觉状态图片生成完成", "visual_state.generation.failed": "视觉状态图片生成失败",
    "clip.prompt.build.completed": "Clip 提示词构建完成", "clip.prompt.build.failed": "Clip 提示词构建失败",
    "clip.prompt.optimize.completed": "H3 提示词优化完成", "clip.prompt.optimize.failed": "H3 提示词优化失败",
    "preflight.repair.completed": "Preflight 修复完成", "preflight.repair.failed": "Preflight 修复失败",
    "clip.generation.completed": "视频生成完成", "clip.generation.failed": "视频生成失败",
    "clip.regeneration.completed": "视频重新生成完成",
    "clip.result.recovery.completed": "视频结果恢复完成", "clip.result.recovery.failed": "视频结果恢复失败",
    "shot.assembly.completed": "视频合并完成", "shot.assembly.failed": "视频合并失败",
    "shot.generation.completed": "视频生成完成", "shot.generation.failed": "视频生成失败",
    "batch.generation.completed": "批量生成完成", "batch.generation.failed": "批量生成失败",
    "task.review.required": "需要人工审核", "comfyui.connection.failed": "连接失败",
    "image.review.passed": "图片评审通过", "image.review.warning": "图片评审提醒", "image.review.failed": "图片评审未通过",
    "image.review.error": "图片评审异常",
    "image.generation.completed": "图片生成完成", "image.generation.failed": "图片生成失败",
    "example.import.completed": "导入完成", "example.import.failed": "导入失败",
}

ERROR_SUMMARIES = {
    "SILENT_CLIP_NOT_COVERED": "当前导演合同尚不支持无对白 Clip",
    "SILENT_ANCHOR_RELATION_MUST_BE_NULL": "无对白 Clip 的 Anchor 不应关联对白",
    "ANCHOR_RELATION_INVALID": "Anchor 与对白的到达关系不合法",
    "PHASE_B_PREFLIGHT_FAILED": "Phase B 执行合同检查未通过",
    "PHASE_B_DIRECTOR_FAILED": "Phase B 导演规划请求失败",
    "DIALOGUE_DUPLICATED_IN_PROMPT": "台词重复校验未通过",
    "DIALOGUE_EXACT_TEXT_OCCURRENCE_INVALID": "台词出现次数不符合要求",
    "DIALOGUE_ORDER_INVALID": "台词顺序不符合要求",
    "DIALOGUE_SPEAKER_MISSING": "台词缺少说话角色",
    "DIALOGUE_SPEAKER_TIMING_AUTHORITY_INVALID": "台词角色或时间校验未通过",
    "DIALOGUE_DURATION_INSUFFICIENT": "台词时长不足",
    "DIALOGUE_PROMPT_AUDIT_FAILED": "台词提示词校验未通过",
    "DIALOGUE_TIMELINE_UNAVAILABLE": "台词时间线尚未准备好",
    "OFFICIAL_DIALOGUE_TIMELINE_INCOMPLETE": "台词时间线不完整",
    "PICTURE_MAPPING_AUDIT_FAILED": "画面引用校验未通过",
    "PHANTOM_PICTURE_REFERENCE": "提示词引用了不存在的画面",
    "PHYSICAL_PICTURE_REFERENCE_MISSING": "提示词缺少必要的画面引用",
    "PHYSICAL_PICTURE_TIME_MISMATCH": "画面引用时间不匹配",
    "PREFLIGHT_FAIL": "视频生成前检查未通过",
    "LLM_TRANSPORT_ERROR": "提示词服务暂时不可用",
    "COMFYUI_CONNECTION_FAILED": "ComfyUI 连接不可用",
}
_ERROR_CODE = re.compile(r"\b[A-Z][A-Z0-9_]{5,}\b")
_INTERNAL_CODE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+){2,}\b")

_UUID = re.compile(r"(?i)\b(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32})\b")
_PRIVATE = re.compile(
    r"(?i)(?:traceback|file\s+\"|(?:api[_ -]?key|token|secret|password|authorization|bearer)\b|"
    r"(?:https?://|data:|sk-[\w-]+|\b\d{5,}:[A-Za-z0-9_-]{8,}\b)|"
    r"(?:[A-Za-z]:\\|/(?:[A-Za-z0-9_.-]+/){1,})|"
    r"(?:sqlalchemy|sqlite|psycopg|operationalerror|integrityerror|programmingerror|databaseerror|"
    r"constraint failed|duplicate key|no such table|sql statement|[A-Za-z]+Error:)|"
    r"(?:\b(?:select|insert|update|delete)\b.{0,30}\b(?:from|into|set)\b))"
)
VIDEO_FAILURES = {"clip.generation.failed", "clip.result.recovery.failed", "shot.generation.failed"}


def _safe_text(value, limit=100):
    if not isinstance(value, str):
        return None
    value = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", value).split()).strip()
    if (not value or value.startswith(("{", "[")) or _UUID.search(value)
            or _PRIVATE.search(value) or _ERROR_CODE.search(value) or _INTERNAL_CODE.search(value)):
        return None
    return value[:limit]


def _positive_index(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if 0 < number < 100000 and str(value).strip() in {str(number), f"{number}.0"} else None
    except (TypeError, ValueError):
        return None


def _nonnegative_count(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if 0 <= number < 100000 and str(value).strip() in {str(number), f"{number}.0"} else None
    except (TypeError, ValueError):
        return None


def _seconds(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and 0 < number < 86400 else None
    except (TypeError, ValueError):
        return None


def _time_text(seconds):
    if seconds is None:
        return None
    rounded = round(seconds)
    if rounded >= 60:
        minutes, rest = divmod(rounded, 60)
        return f"{minutes}分{rest}秒" if rest else f"{minutes}分"
    return f"{seconds:g}秒"


def _details(row):
    try:
        result = json.loads(row.details_json or "{}")
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def _naive_utc(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _matching_prompt_error(plan_text, row, details):
    """Read the exact saved AI call when the event snapshot lacks its error code."""
    try:
        plan = json.loads(plan_text or "{}")
        calls = plan.get("ai_calls") or []
        clip = _positive_index(details.get("clip_index"))
        for call in reversed(calls):
            if not isinstance(call, dict) or str(call.get("step")) != str(details.get("stage")):
                continue
            if _positive_index(call.get("clip_index")) != clip:
                continue
            created = datetime.fromisoformat(str(call.get("created_at")))
            if _naive_utc(created) != _naive_utc(row.timestamp):
                continue
            parsed = call.get("parsed_result") if isinstance(call.get("parsed_result"), dict) else {}
            return call.get("error_message") or parsed.get("error_code") or parsed.get("issues")
    except (TypeError, ValueError, AttributeError):
        return None
    return None


def _error_summary(*values):
    codes = []
    for value in values:
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, str):
                codes.extend(_ERROR_CODE.findall(item))
    translated = list(dict.fromkeys(ERROR_SUMMARIES[code] for code in codes if code in ERROR_SUMMARIES))
    if translated:
        return "；".join(translated[:2]), codes
    for value in values:
        safe = _safe_text(value)
        if safe:
            return safe, codes
    return None, codes


def resolve_business_context(db, row):
    """One narrow query for a real event; simulations never read business rows."""
    if row.is_test:
        return {}
    details = _details(row)
    pseudo_clip = bool(row.shot_id and isinstance(row.clip_id, str)
                       and row.clip_id.startswith(f"{row.shot_id}:clip:"))
    needs_task_clip = bool(row.task_id and not _positive_index(details.get("clip_index")) and not pseudo_clip)
    needs_failure = bool(row.task_id and row.event_type in VIDEO_FAILURES)
    needs_task_metadata = needs_task_clip or needs_failure
    if row.shot_id:
        prompt_failure = row.event_type == "clip.prompt.build.failed"
        columns = [Shot.index, Chapter.number, Novel.title, Task.started_at, Task.completed_at, Task.current_step]
        if prompt_failure:
            columns.append(Shot.video_director_plan)
        if needs_task_metadata:
            columns.extend([Task.metadata_json, Task.shot_id])
        if needs_failure:
            columns.append(Task.error_message)
        result = (db.query(*columns)
                  .join(Chapter, Shot.chapter_id == Chapter.id)
                  .join(Novel, Chapter.novel_id == Novel.id)
                  .outerjoin(Task, Task.id == row.task_id)
                  .filter(Shot.id == row.shot_id).first())
    elif row.chapter_id:
        columns = [Chapter.number, Novel.title, Task.started_at, Task.completed_at, Task.current_step]
        if needs_task_metadata:
            columns.extend([Task.metadata_json, Task.shot_id])
        if needs_failure:
            columns.append(Task.error_message)
        result = (db.query(*columns)
                  .join(Novel, Chapter.novel_id == Novel.id)
                  .outerjoin(Task, Task.id == row.task_id)
                  .filter(Chapter.id == row.chapter_id).first())
    elif row.novel_id:
        columns = [Novel.title, Task.started_at, Task.completed_at, Task.current_step]
        if needs_task_metadata:
            columns.extend([Task.metadata_json, Task.shot_id])
        if needs_failure:
            columns.append(Task.error_message)
        result = (db.query(*columns)
                  .outerjoin(Task, Task.id == row.task_id)
                  .filter(Novel.id == row.novel_id).first())
    elif row.task_id:
        columns = [Task.started_at, Task.completed_at, Task.current_step]
        if needs_task_metadata:
            columns.extend([Task.metadata_json, Task.shot_id])
        if needs_failure:
            columns.append(Task.error_message)
        result = db.query(*columns).filter(Task.id == row.task_id).first()
    else:
        return {}
    if not result:
        return {}
    values = tuple(result)
    keys = (["shot_number", "chapter_number", "novel_name"] if row.shot_id else
            ["chapter_number", "novel_name"] if row.chapter_id else
            ["novel_name"] if row.novel_id else []) + ["started_at", "completed_at", "current_step"]
    context = dict(zip(keys, values))
    if row.shot_id and row.event_type == "clip.prompt.build.failed":
        context["prompt_error"] = _matching_prompt_error(values[len(keys)], row, details)
    if needs_task_metadata:
        offset = len(keys) + (1 if row.shot_id and row.event_type == "clip.prompt.build.failed" else 0)
        try:
            meta = json.loads(values[offset] or "{}")
            task_shot_id = values[offset + 1]
            if isinstance(meta, dict) and (not row.shot_id or task_shot_id == row.shot_id):
                context["clip_number"] = _positive_index(meta.get("clip_index"))
                # Do not describe a historical failure using a newer retry's state.
                same_attempt = not (context.get("started_at") and row.timestamp
                                    and _naive_utc(context["started_at"]) > _naive_utc(row.timestamp))
                if needs_failure and same_attempt:
                    context["task_error"] = values[offset + 2]
                    mode = meta.get("capability") or (meta.get("execution_contract") or {}).get("capability")
                    context["generation_mode"] = mode if mode in {"GENERATE", "EXTEND", "TEMPORAL_EXTEND"} else None
                    phase_b = meta.get("h3_phase_b") or {}
                    if phase_b.get("status") == "FAILED":
                        compiled = phase_b.get("compiler_result")
                        context["failure_stage"] = (
                            "Phase B Compiler" if compiled and compiled.get("status") != "CANDIDATE_FOR_REVIEW" else
                            "Phase B Preflight" if phase_b.get("preflight") else
                            "Phase B 输入准备" if phase_b.get("llm_call_count") == 0 else
                            "#13 Phase B 导演规划")
                    else:
                        context["failure_step"] = _safe_text(context.get("current_step"), 80)
        except (TypeError, ValueError, IndexError):
            pass
    return context


def format_notification(row, context=None):
    """Same plain Unicode message for Telegram and Feishu text adapters."""
    context = context or {}
    details = _details(row)
    code = row.event_type
    shot = _positive_index(context.get("shot_number")) or _positive_index(details.get("shot_index"))
    clip = _positive_index(context.get("clip_number")) or _positive_index(details.get("clip_index"))
    if clip is None and isinstance(row.clip_id, str) and row.shot_id:
        prefix = f"{row.shot_id}:clip:"
        if row.clip_id.startswith(prefix):
            clip = _positive_index(row.clip_id[len(prefix):])
    chapter = _positive_index(context.get("chapter_number")) or _positive_index(details.get("chapter_number"))
    novel = _safe_text(context.get("novel_name") or details.get("novel_name"), 60)
    if code == "task.review.required":
        icon = "⚠️"
    elif code.endswith((".failed", ".error")):
        icon = "❌"
    elif code.startswith("preflight.repair") and code.endswith(".completed"):
        icon = "🔧"
    else:
        icon = "✅"
    if code.startswith("comfyui."):
        target = "ComfyUI"
    elif code.startswith("example.import"):
        target = "示例小说"
    elif code.startswith("batch."):
        target = ""
    elif shot:
        target = f"Shot {shot}" + (f" · C{clip}" if clip and code.startswith(("clip.", "preflight.")) else "")
    elif clip:
        target = f"C{clip}"
    elif code.startswith("shot."):
        target = "Shot"
    elif code.startswith("clip.prompt"):
        target = ""
    elif code.startswith(("clip.", "preflight.")):
        target = "Clip"
    elif code.startswith("visual_state."):
        target = ""
    elif code.startswith("image."):
        target = ""
    else:
        target = "任务"
    error_summary, error_codes = (_error_summary(details.get("error_code"), context.get("prompt_error"), row.message, context.get("task_error"))
                                  if code.endswith((".failed", ".error")) else (None, []))
    prompt_stage = code == "clip.generation.failed" and (
        any(value.startswith("DIALOGUE_") or value in {"PICTURE_MAPPING_AUDIT_FAILED", "PHANTOM_PICTURE_REFERENCE"}
            for value in error_codes)
        or "H3 提示词构建" in str(context.get("current_step") or ""))
    label = "生成失败" if prompt_stage else LABELS.get(code, EVENT_REGISTRY[code].name)
    title = f"{icon} NovelFlow｜{target + ' ' if target else ''}{label}"
    lines = [title]
    if row.is_test:
        lines.extend(["", "🧪 开发模拟事件"])
    if novel or chapter:
        lines.append("")
        if novel:
            lines.append(f"📖 小说：{novel}")
        if chapter:
            lines.append(f"📚 章节：第 {chapter} 章")

    facts = []
    if code.startswith("shot.planning"):
        facts.append("规划结果：" + ("完成" if code.endswith(".completed") else "失败"))
    state = _positive_index(details.get("visual_state_index")) or _positive_index(row.visual_state_id)
    if code.startswith("visual_state."):
        if state:
            facts.append(f"视觉状态：第 {state} 个")
        facts.append("生成结果：" + ("完成" if code.endswith(".completed") else "失败"))
    if code.startswith("clip.prompt.optimize"):
        facts.append("优化结果：" + ("完成" if code.endswith(".completed") else "失败"))
    if code.startswith("preflight."):
        levels = details.get("repair_levels")
        levels = [value for value in levels if isinstance(value, str) and value in {"L0", "L1"}] if isinstance(levels, list) else []
        if not levels and _positive_index(details.get("l1_invocations")):
            levels = ["L1"]
        if levels:
            facts.append(f"修复方式：{'、'.join(dict.fromkeys(levels))}")
        facts.append("最终检查：" + ("通过" if code.endswith(".completed") else "未通过"))
    if code.startswith("shot.assembly"):
        count = _nonnegative_count(details.get("clip_count"))
        if count is not None:
            facts.append(f"Clip 数量：{count}")
        facts.append("合并结果：" + ("完成" if code.endswith(".completed") else "失败"))
    if code.startswith("batch."):
        task_counts = re.fullmatch(r"完成：成功 (\d+)，失败 (\d+)，取消 (\d+)", context.get("current_step") or "")
        if task_counts:
            successful, failed, cancelled = (int(value) for value in task_counts.groups())
            details = {**details, "success_count": successful, "failure_count": failed,
                       "cancelled_count": cancelled, "total_count": successful + failed + cancelled}
        for field, label in (("success_count", "成功"), ("failure_count", "失败"), ("total_count", "总")):
            count = _nonnegative_count(details.get(field))
            if count is not None:
                facts.append(f"{label}数量：{count}")
        cancelled = _nonnegative_count(details.get("cancelled_count"))
        if cancelled is not None:
            facts.append(f"取消数量：{cancelled}")
    if code.startswith("example.import"):
        count = _nonnegative_count(details.get("chapter_count"))
        if count is not None:
            facts.append(f"章节数量：{count}")
    if code.startswith("image.review"):
        facts.append("评审结果：" + ("通过" if code.endswith(".passed") else "提醒" if code.endswith(".warning") else "异常" if code.endswith(".error") else "未通过"))
    if code.startswith("image.generation"):
        facts.append("生成结果：" + ("完成" if code.endswith(".completed") else "失败"))

    elapsed = _seconds(details.get("elapsed_time"))
    if elapsed is None:
        try:
            milliseconds = float(details.get("duration_ms"))
            elapsed = milliseconds / 1000 if math.isfinite(milliseconds) and 0 < milliseconds < 86400000 else None
        except (TypeError, ValueError):
            pass
    if elapsed is None and context.get("started_at") and context.get("completed_at"):
        try:
            elapsed = _seconds((context["completed_at"] - context["started_at"]).total_seconds())
        except (TypeError, ValueError):
            pass
    if elapsed is not None:
        facts.append(f"⏱ 耗时：{_time_text(elapsed)}")
    if code.startswith(("clip.generation", "clip.regeneration", "clip.result.recovery", "shot.generation")):
        video = _seconds(details.get("actual_duration")) or _seconds(details.get("video_duration"))
        if video is not None:
            facts.append(f"🎞 视频时长：{video:g}秒")

    default = EVENT_REGISTRY[code].description
    summary = error_summary or _safe_text(details.get("summary"))
    if summary == default:
        summary = None
    if code.endswith((".failed", ".error")):
        stage = {"11": "H3 提示词构建", "12": "H3 提示词构建", "13": "H3 提示词构建",
                 "14": "H3 提示词优化", "shot_video.merge": "Shot 视频合并",
                 "video_director.planning": "Shot 规划"}.get(str(details.get("stage")))
        if code.startswith("preflight.repair"):
            stage = "H3 Preflight"
        if code == "clip.prompt.build.failed" or prompt_stage:
            stage = "H3 提示词构建"
        if code in VIDEO_FAILURES:
            stage = context.get("failure_stage") or stage or context.get("failure_step") or "未知（查看任务记录）"
            summary = summary or "未取得可安全展示的错误摘要，请查看任务详情"
        if stage:
            facts.append(f"阶段：{stage}")
        if summary:
            facts.append(f"原因：{summary}")
        if code in VIDEO_FAILURES:
            # Only the explicit task identifier is allowed; arbitrary UUIDs,
            # exception text, paths and credentials still fail _safe_text.
            task_id = str(row.task_id or "")
            facts.append("任务 ID：" + (task_id if _UUID.fullmatch(task_id) else "未知"))
            facts.append("生成模式：" + (context.get("generation_mode") or "UNKNOWN"))
        if code == "clip.generation.failed":
            facts.append("结果：" + ("视频未生成" if prompt_stage else "生成任务已失败"))
        if code == "clip.prompt.optimize.failed" and details.get("blocking_findings"):
            facts.append("结果：已阻止视频生成")
    elif summary and code.startswith(("shot.planning", "clip.prompt", "preflight.repair", "shot.assembly")):
        facts.append(f"处理结果：{summary}")
    if code == "comfyui.connection.failed" and row.timestamp:
        stamp = row.timestamp
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        facts.append(f"发生时间：{stamp.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC")
    if facts:
        lines.extend(["", *facts])
    return "\n".join(lines)
