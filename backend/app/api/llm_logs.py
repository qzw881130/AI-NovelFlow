"""
LLM 调用日志 API 路由

LLM 调用日志相关的路由定义
"""
import json
import re
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.core.database import get_db
from app.core.config import get_settings
from app.models.llm_log import LLMLog
from app.repositories import LLMLogRepository
from app.constants.prompt_template import PROMPT_TEMPLATE_FILE_NUMBERS

router = APIRouter()


class LLMLogExportRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)

LLM_LOG_TASK_CATEGORY_TYPES = {
    "story_context": ["story_world_context_recommender"],
    "style_design": ["style"],
    "asset_parse": ["parse_characters", "parse_scenes", "parse_props"],
    "asset_generation": ["generate_character_appearance"],
    "shot_planning": ["split_chapter"],
    "shot_image": ["shot_image_prompt"],
    "video_director": ["video_mode_recommender", "keyframe_description", "keyframe_planner", "keyframe_transition"],
    "keyframe_image": ["keyframe_image_prompt"],
    "video_generation": ["expand_video_prompt", "h3_single_frame_prompt", "h3_first_last_frame_prompt", "h3_multi_keyframe_prompt"],
}

LLM_LOG_TASK_LABELS = {
    "story_world_context_recommender": "故事上下文-故事世界上下文推荐",
    "style": "风格设计-风格提示词",
    "parse_characters": "素材解析-解析角色",
    "parse_props": "素材解析-解析道具",
    "parse_scenes": "素材解析-解析场景",
    "generate_character_appearance": "素材生成-生成角色外貌",
    "split_chapter": "分镜规划-拆分分镜",
    "shot_image_prompt": "分镜生图-主分镜图提示词",
    "video_mode_recommender": "视频导演-视频模式推荐",
    "keyframe_description": "视频导演-关键帧描述",
    "keyframe_planner": "视频导演-关键帧规划",
    "keyframe_image_prompt": "关键帧生图-关键帧生图提示词",
    "keyframe_transition": "视频导演-关键帧过渡规划",
    "expand_video_prompt": "视频生成-扩写视频提示词",
    "h3_single_frame_prompt": "视频生成-H3单帧视频提示词",
    "h3_first_last_frame_prompt": "视频生成-H3首尾帧视频提示词",
    "h3_multi_keyframe_prompt": "视频生成-H3多关键帧视频提示词",
}

LLM_TASK_TEMPLATE_TYPES = {
    "story_world_context_recommender": "story_world_context_recommender",
    "style": "style",
    "parse_characters": "character_parse",
    "parse_props": "prop_parse",
    "parse_scenes": "scene_parse",
    "generate_character_appearance": "character",
    "split_chapter": "chapter_split",
    "shot_image_prompt": "shot_image_prompt",
    "video_mode_recommender": "video_mode_recommender",
    "keyframe_description": "keyframe_description",
    "keyframe_planner": "keyframe_planner",
    "keyframe_image_prompt": "keyframe_image_prompt",
    "keyframe_transition": "keyframe_transition",
    "expand_video_prompt": "expand_video_prompt",
    "h3_single_frame_prompt": "h3_single_frame_prompt",
    "h3_first_last_frame_prompt": "h3_first_last_frame_prompt",
    "h3_multi_keyframe_prompt": "h3_multi_keyframe_prompt",
}

# 上海时区 (东八区)
SHANGHAI_TZ = timezone(timedelta(hours=8))
UTC_TZ = timezone.utc


def get_llmlog_repo(db: Session = Depends(get_db)) -> LLMLogRepository:
    """获取 LLMLogRepository 实例"""
    return LLMLogRepository(db)

def to_shanghai_time(dt: datetime) -> str:
    """将时间转换为上海时间字符串
    
    处理各种时区情况：
    - SQLite 的 func.now() 返回的是 UTC 时间（无时区）
    - 如果时间是 naive（无时区），假设为 UTC 时间，然后转为上海时间
    - 如果时间是 aware（有时区），直接转为上海时间
    """
    if not dt:
        return None
    
    if dt.tzinfo is None:
        # Naive 时间，先添加 UTC 时区，然后转为上海时间
        dt = dt.replace(tzinfo=UTC_TZ)
    
    return dt.astimezone(SHANGHAI_TZ).isoformat()


def _to_shanghai_datetime(dt: datetime) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(SHANGHAI_TZ)


def _safe_export_filename_part(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(value or fallback).strip())
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(" .")
    return cleaned or fallback


def _pretty_json_text(value: str) -> str:
    if not value:
        return "-"
    try:
        return json.dumps(json.loads(value), ensure_ascii=False, indent=2)
    except (TypeError, json.JSONDecodeError):
        return value


def _log_request_text(log: LLMLog) -> str:
    if log.request_info:
        return _pretty_json_text(log.request_info)
    return json.dumps({
        "provider": log.provider,
        "model": log.model,
        "usedProxy": bool(log.used_proxy),
        "durationSeconds": log.duration,
        "taskType": log.task_type,
        "promptTemplateName": log.prompt_template_name,
        "novelId": log.novel_id,
        "chapterId": log.chapter_id,
        "characterId": log.character_id,
        "payload": {
            "model": log.model,
            "messages": [
                {"role": "system", "content": log.system_prompt or ""},
                {"role": "user", "content": log.user_prompt or ""},
            ],
        },
    }, ensure_ascii=False, indent=2)


def _apply_log_filters(query, provider=None, model=None, category=None, task_type=None, status=None, novel_id=None):
    if provider:
        query = query.filter(LLMLog.provider == provider)
    if model:
        query = query.filter(LLMLog.model == model)
    if task_type:
        query = query.filter(LLMLog.task_type == task_type)
    elif category and LLM_LOG_TASK_CATEGORY_TYPES.get(category):
        query = query.filter(LLMLog.task_type.in_(LLM_LOG_TASK_CATEGORY_TYPES[category]))
    if status:
        query = query.filter(LLMLog.status == status)
    if novel_id:
        query = query.filter(LLMLog.novel_id == novel_id)
    return query


def reconcile_stale_pending_llm_logs(db: Session) -> int:
    timeout = int(getattr(get_settings(), "LLM_TIMEOUT", 300) or 300)
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=timeout + 60)
    stale_logs = db.query(LLMLog).filter(
        LLMLog.status == "pending",
        LLMLog.created_at < cutoff,
    ).all()
    for log in stale_logs:
        log.status = "error"
        log.error_message = "LLM 调用超过配置超时时间仍未完成，可能是请求中断或后台进程已退出"
    if stale_logs:
        db.commit()
    return len(stale_logs)


@router.get("/")
def get_llm_logs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    provider: Optional[str] = Query(None, description="LLM厂商筛选"),
    model: Optional[str] = Query(None, description="模型筛选"),
    category: Optional[str] = Query(None, description="分类筛选"),
    task_type: Optional[str] = Query(None, description="任务类型筛选"),
    status: Optional[str] = Query(None, description="状态筛选: pending/success/error"),
    novel_id: Optional[str] = Query(None, description="小说ID筛选"),
    llmlog_repo: LLMLogRepository = Depends(get_llmlog_repo),
    db: Session = Depends(get_db),
):
    """获取LLM调用日志列表"""
    reconcile_stale_pending_llm_logs(db)
    logs, total = llmlog_repo.list_paginated_summaries(
        page=page,
        page_size=page_size,
        provider=provider,
        model=model,
        task_type=task_type,
        task_types=LLM_LOG_TASK_CATEGORY_TYPES.get(category or ""),
        status=status,
        novel_id=novel_id
    )
    
    return {
        "success": True,
        "data": {
            "items": [
                {
                    "id": log.id,
                    "created_at": to_shanghai_time(log.created_at),
                    "provider": log.provider,
                    "model": log.model,
                    "prompt_template_name": log.prompt_template_name,
                    "system_prompt": "",
                    "user_prompt": log.user_prompt or "",
                    "request_info": "",
                    "response": "",
                    "status": log.status,
                    "error_message": log.error_message,
                    "task_type": log.task_type,
                    "novel_id": log.novel_id,
                    "chapter_id": log.chapter_id,
                    "character_id": log.character_id,
                    "used_proxy": log.used_proxy,
                    "duration": log.duration,
                    "metrics": log.usage_metrics,
                }
                for log in logs
            ],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size
            }
        }
    }


@router.get("/filters")
def get_log_filters(llmlog_repo: LLMLogRepository = Depends(get_llmlog_repo)):
    """获取日志筛选选项"""
    providers = llmlog_repo.get_distinct_providers()
    models = llmlog_repo.get_distinct_models()
    task_types = llmlog_repo.get_distinct_task_types()
    
    return {
        "success": True,
        "data": {
            "providers": providers,
            "models": models,
            "task_types": task_types
        }
    }


@router.get("/stats")
def get_llm_log_stats(
    group_by: str = Query("hour", pattern="^(day|hour|minute)$", description="分组粒度: day/hour/minute"),
    range_value: int = Query(1, ge=1, le=31, description="范围值：day=7/31, hour=1/3, minute=1"),
    provider: Optional[str] = Query(None, description="LLM厂商筛选"),
    model: Optional[str] = Query(None, description="模型筛选"),
    category: Optional[str] = Query(None, description="分类筛选"),
    task_type: Optional[str] = Query(None, description="任务类型筛选"),
    status: Optional[str] = Query(None, description="状态筛选: pending/success/error"),
    novel_id: Optional[str] = Query(None, description="小说ID筛选"),
    db: Session = Depends(get_db),
):
    """按时间分组统计 LLM 调用次数。"""
    now = datetime.now(SHANGHAI_TZ)
    if group_by == "day":
        days = 31 if range_value == 31 else 7
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        buckets = [start + timedelta(days=i) for i in range(days)]
        key_format = "%Y-%m-%d"
        label_format = "%m/%d"
    elif group_by == "hour":
        hours = 72 if range_value == 3 else 24
        start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
        buckets = [start + timedelta(hours=i) for i in range(hours)]
        key_format = "%Y-%m-%d %H:00"
        label_format = "%m/%d %H:00" if hours > 24 else "%H:00"
    else:
        minutes = 60
        start = now.replace(second=0, microsecond=0) - timedelta(minutes=minutes - 1)
        buckets = [start + timedelta(minutes=i) for i in range(minutes)]
        key_format = "%Y-%m-%d %H:%M"
        label_format = "%H:%M"

    counts = {bucket.strftime(key_format): 0 for bucket in buckets}
    start_utc = start.astimezone(UTC_TZ).replace(tzinfo=None)
    query = db.query(LLMLog.created_at).filter(LLMLog.created_at >= start_utc)
    query = _apply_log_filters(query, provider, model, category, task_type, status, novel_id)

    for (created_at,) in query.all():
        shanghai_dt = _to_shanghai_datetime(created_at)
        if not shanghai_dt or shanghai_dt < start:
            continue
        if group_by == "day":
            bucket_dt = shanghai_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        elif group_by == "hour":
            bucket_dt = shanghai_dt.replace(minute=0, second=0, microsecond=0)
        else:
            bucket_dt = shanghai_dt.replace(second=0, microsecond=0)
        key = bucket_dt.strftime(key_format)
        if key in counts:
            counts[key] += 1

    items = [
        {
            "key": bucket.strftime(key_format),
            "label": bucket.strftime(label_format),
            "count": counts[bucket.strftime(key_format)],
        }
        for bucket in buckets
    ]
    return {
        "success": True,
        "data": {
            "group_by": group_by,
            "range_value": range_value,
            "total": sum(item["count"] for item in items),
            "items": items,
        },
    }


@router.get("/token-stats")
def get_llm_log_token_stats(
    group_by: str = Query("hour", pattern="^(day|hour|minute)$", description="分组粒度: day/hour/minute"),
    range_value: int = Query(1, ge=1, le=31, description="范围值：day=7/31, hour=1/3, minute=1"),
    provider: Optional[str] = Query(None, description="LLM厂商筛选"),
    model: Optional[str] = Query(None, description="模型筛选"),
    category: Optional[str] = Query(None, description="分类筛选"),
    task_type: Optional[str] = Query(None, description="任务类型筛选"),
    status: Optional[str] = Query(None, description="状态筛选: pending/success/error"),
    novel_id: Optional[str] = Query(None, description="小说ID筛选"),
    db: Session = Depends(get_db),
):
    """按时间分组统计 LLM 输入和输出 Token。"""
    now = datetime.now(SHANGHAI_TZ)
    if group_by == "day":
        bucket_count = 31 if range_value == 31 else 7
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=bucket_count - 1)
        buckets = [start + timedelta(days=i) for i in range(bucket_count)]
        key_format = "%Y-%m-%d"
        label_format = "%m/%d"
    elif group_by == "hour":
        bucket_count = 72 if range_value == 3 else 24
        start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=bucket_count - 1)
        buckets = [start + timedelta(hours=i) for i in range(bucket_count)]
        key_format = "%Y-%m-%d %H:00"
        label_format = "%m/%d %H:00" if bucket_count > 24 else "%H:00"
    else:
        bucket_count = 60
        start = now.replace(second=0, microsecond=0) - timedelta(minutes=bucket_count - 1)
        buckets = [start + timedelta(minutes=i) for i in range(bucket_count)]
        key_format = "%Y-%m-%d %H:%M"
        label_format = "%H:%M"

    token_counts = {
        bucket.strftime(key_format): {"input_tokens": 0, "output_tokens": 0}
        for bucket in buckets
    }
    start_utc = start.astimezone(UTC_TZ).replace(tzinfo=None)
    query = db.query(LLMLog.created_at, LLMLog.usage_metrics).filter(LLMLog.created_at >= start_utc)
    query = _apply_log_filters(query, provider, model, category, task_type, status, novel_id)

    for created_at, usage_metrics in query.all():
        shanghai_dt = _to_shanghai_datetime(created_at)
        if not shanghai_dt or shanghai_dt < start:
            continue
        if group_by == "day":
            bucket_dt = shanghai_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        elif group_by == "hour":
            bucket_dt = shanghai_dt.replace(minute=0, second=0, microsecond=0)
        else:
            bucket_dt = shanghai_dt.replace(second=0, microsecond=0)
        key = bucket_dt.strftime(key_format)
        if key not in token_counts or not isinstance(usage_metrics, dict):
            continue
        for field in ("input_tokens", "output_tokens"):
            value = usage_metrics.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                token_counts[key][field] += int(value)

    items = [
        {
            "key": bucket.strftime(key_format),
            "label": bucket.strftime(label_format),
            **token_counts[bucket.strftime(key_format)],
        }
        for bucket in buckets
    ]
    return {
        "success": True,
        "data": {
            "group_by": group_by,
            "range_value": range_value,
            "total_input_tokens": sum(item["input_tokens"] for item in items),
            "total_output_tokens": sum(item["output_tokens"] for item in items),
            "items": items,
        },
    }


@router.post("/export-selected", response_class=StreamingResponse)
def export_selected_llm_logs(
    request: LLMLogExportRequest,
    db: Session = Depends(get_db),
):
    """将所选日志的 LLM 参数与响应分别合并为单个 TXT 后打包。"""
    requested_ids = list(dict.fromkeys(request.ids))
    logs = db.query(LLMLog).filter(LLMLog.id.in_(requested_ids)).all()
    logs_by_id = {log.id: log for log in logs}
    ordered_logs = [logs_by_id[log_id] for log_id in requested_ids if log_id in logs_by_id]
    if not ordered_logs:
        raise HTTPException(status_code=404, detail="未找到所选大模型日志")

    buffer = BytesIO()
    used_names: set[str] = set()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for log in ordered_logs:
            created_at = _to_shanghai_datetime(log.created_at)
            time_part = created_at.strftime("%Y-%m-%d_%H-%M-%S") if created_at else "unknown-time"
            template_type = LLM_TASK_TEMPLATE_TYPES.get(log.task_type)
            file_number = PROMPT_TEMPLATE_FILE_NUMBERS.get(template_type, "00")
            task_name = LLM_LOG_TASK_LABELS.get(log.task_type, f"其他任务-{log.task_type or '未知'}")
            task_part = _safe_export_filename_part(f"{file_number}-{task_name}", "00-其他任务-未知")
            template_part = _safe_export_filename_part(log.prompt_template_name or "未记录模板", "未记录模板")
            base_name = f"{time_part}--{task_part}--{template_part}"
            filename = f"{base_name}.txt"
            suffix = 2
            while filename in used_names:
                filename = f"{base_name} ({suffix}).txt"
                suffix += 1
            used_names.add(filename)

            content = "\n".join([
                f"日志时间：{to_shanghai_time(log.created_at) or '-'}",
                f"任务：{task_part}",
                f"提示词模板：{log.prompt_template_name or '-'}",
                f"Provider / Model：{log.provider} / {log.model}",
                "",
                "LLM 参数",
                "=" * 80,
                _log_request_text(log),
                "",
                "LLM 响应",
                "=" * 80,
                _pretty_json_text(log.response or ""),
                "",
            ])
            archive.writestr(filename, content)

    buffer.seek(0)
    archive_name = f"llm_logs_{datetime.now(SHANGHAI_TZ).strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{archive_name}"'},
    )


@router.get("/{log_id}")
def get_llm_log_detail(
    log_id: str, 
    llmlog_repo: LLMLogRepository = Depends(get_llmlog_repo)
):
    """获取单个日志详情"""
    log = llmlog_repo.get_by_id(log_id)
    
    if not log:
        return {"success": False, "message": "日志不存在"}
    
    return {
        "success": True,
        "data": {
            "id": log.id,
            "created_at": to_shanghai_time(log.created_at),
            "provider": log.provider,
            "model": log.model,
            "prompt_template_name": log.prompt_template_name,
            "system_prompt": log.system_prompt,
            "user_prompt": log.user_prompt,
            "request_info": log.request_info,
            "response": log.response,
            "status": log.status,
            "error_message": log.error_message,
            "task_type": log.task_type,
            "novel_id": log.novel_id,
            "chapter_id": log.chapter_id,
            "character_id": log.character_id,
            "used_proxy": log.used_proxy,
            "duration": log.duration,
            "metrics": log.usage_metrics,
        }
    }
