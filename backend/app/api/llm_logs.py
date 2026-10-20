from app.services.llm.multimodal import log_image_inputs
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
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.repositories import LLMLogRepository
from app.constants.prompt_template import PROMPT_TEMPLATE_FILE_NUMBERS
from app.services.llm.cancellation import LLM_CANCELLED_MESSAGE

router = APIRouter()


class LLMLogExportRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


class LLMLogCancelRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


@router.post("/cancel-selected")
def cancel_selected_llm_logs(request: LLMLogCancelRequest, db: Session = Depends(get_db)):
    """Only terminate selected pending calls; preserve completed logs and history."""
    ids = list(dict.fromkeys(request.ids))
    logs = db.query(LLMLog).filter(LLMLog.id.in_(ids)).all()
    if {log.id for log in logs} != set(ids):
        raise HTTPException(status_code=404, detail="所选日志不存在，请刷新后重试")
    cancelled_ids = []
    now = datetime.now(timezone.utc)
    try:
        for log in logs:
            if log.status != "pending":
                continue
            created = log.created_at
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            changed = db.query(LLMLog).filter(
                LLMLog.id == log.id, LLMLog.status == "pending",
            ).update({
                LLMLog.status: "error",
                LLMLog.error_message: LLM_CANCELLED_MESSAGE,
                LLMLog.duration: max(0, (now - created).total_seconds()) if created else None,
            }, synchronize_session=False)
            if changed:
                cancelled_ids.append(log.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"success": True, "data": {
        "cancelled_ids": cancelled_ids,
        "skipped_ids": [id_ for id_ in ids if id_ not in cancelled_ids],
    }}

LLM_LOG_TASK_CATEGORY_TYPES = {
    "story_context": ["story_world_context_recommender"],
    "style_design": ["style"],
    "asset_parse": ["parse_characters", "parse_scenes", "parse_props"],
    "asset_generation": ["generate_character_appearance", "generate_scene_setting", "generate_prop_appearance"],
    "shot_planning": ["split_chapter"],
    "shot_image": ["shot_image_prompt"],
    "video_director": ["video_mode_recommender", "keyframe_description", "keyframe_planner", "keyframe_transition", "clip_execution_planner"],
    "keyframe_image": ["temporal_reference_selector", "keyframe_image_prompt", "image_quality_review_prompt"],
    "video_generation": ["expand_video_prompt", "h3_single_frame_prompt", "h3_first_last_frame_prompt", "h3_multi_keyframe_prompt", "h3_multi_keyframe_director_phase_b", "h3_execution_optimizer_prompt", "h3_preflight_repair_prompt"],
}

LLM_LOG_TASK_LABELS = {
    "story_world_context_recommender": "故事上下文-故事世界上下文推荐",
    "style": "风格设计-风格提示词",
    "parse_characters": "素材解析-解析角色",
    "parse_props": "素材解析-解析道具",
    "parse_scenes": "素材解析-解析场景",
    "generate_character_appearance": "素材生成-生成角色外貌",
    "generate_scene_setting": "素材生成-生成场景设定",
    "generate_prop_appearance": "素材生成-生成道具外观",
    "split_chapter": "分镜规划-拆分分镜",
    "shot_image_prompt": "分镜生图-主分镜图提示词",
    "video_mode_recommender": "视频导演-视频模式推荐",
    "keyframe_description": "视频导演-关键帧描述",
    "keyframe_planner": "视频导演-关键帧规划",
    "keyframe_image_prompt": "关键帧生图-关键帧生图提示词",
    "image_quality_review_prompt": "关键帧生图-AI 图片质量评审",
    "temporal_reference_selector": "分镜生图-Temporal Anchor Reference Selector",
    "keyframe_transition": "视频导演-关键帧过渡规划",
    "clip_execution_planner": "视频导演-视频片段执行规划",
    "expand_video_prompt": "视频生成-扩写视频提示词",
    "h3_single_frame_prompt": "视频生成-H3单帧视频提示词",
    "h3_first_last_frame_prompt": "视频生成-H3首尾帧视频提示词",
    "h3_multi_keyframe_prompt": "视频生成-H3多关键帧视频提示词",
    "h3_multi_keyframe_director_phase_b": "视频生成-H3单阶段导演（Phase B）",
    "h3_execution_optimizer_prompt": "视频生成-MiniMax H3 执行提示词优化",
    "h3_preflight_repair_prompt": "视频生成-MiniMax H3 Preflight 自动修复",
}

LLM_TASK_TEMPLATE_TYPES = {
    "story_world_context_recommender": "story_world_context_recommender",
    "style": "style",
    "parse_characters": "character_parse",
    "parse_props": "prop_parse",
    "parse_scenes": "scene_parse",
    "generate_character_appearance": "character",
    "generate_scene_setting": "scene_setting",
    "generate_prop_appearance": "prop_appearance",
    "split_chapter": "chapter_split",
    "shot_image_prompt": "shot_image_prompt",
    "video_mode_recommender": "video_mode_recommender",
    "keyframe_description": "keyframe_description",
    "keyframe_planner": "keyframe_planner",
    "keyframe_image_prompt": "keyframe_image_prompt",
    "image_quality_review_prompt": "image_quality_review_prompt",
    "temporal_reference_selector": "temporal_reference_selector",
    "keyframe_transition": "keyframe_transition",
    "clip_execution_planner": "clip_execution_planner",
    "expand_video_prompt": "expand_video_prompt",
    "h3_single_frame_prompt": "h3_single_frame_prompt",
    "h3_first_last_frame_prompt": "h3_first_last_frame_prompt",
    "h3_multi_keyframe_prompt": "h3_multi_keyframe_prompt",
    "h3_multi_keyframe_director_phase_b": "h3_multi_keyframe_director_phase_b",
    "h3_execution_optimizer_prompt": "h3_execution_optimizer_prompt",
    "h3_preflight_repair_prompt": "h3_preflight_repair_prompt",
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
        "shotId": log.shot_id,
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
    updated_count = 0
    for log in stale_logs:
        # Completion or selected cancellation may have committed after the read.
        updated_count += db.query(LLMLog).filter(
            LLMLog.id == log.id,
            LLMLog.status == "pending",
            LLMLog.created_at < cutoff,
        ).update({
            LLMLog.status: "error",
            LLMLog.error_message: "LLM 调用超过配置超时时间仍未完成，可能是请求中断或后台进程已退出",
        }, synchronize_session=False)
    if stale_logs:
        db.commit()
    return updated_count


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
    novel_titles = dict(db.query(Novel.id, Novel.title).filter(Novel.id.in_(
        {log.novel_id for log in logs if log.novel_id}
    )).all())
    chapters = {chapter.id: chapter for chapter in db.query(Chapter.id, Chapter.number, Chapter.title).filter(
        Chapter.id.in_({log.chapter_id for log in logs if log.chapter_id})
    ).all()}
    shot_indexes = dict(db.query(Shot.id, Shot.index).filter(Shot.id.in_(
        {log.shot_id for log in logs if log.shot_id}
    )).all())
    
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
                    "novel_title": novel_titles.get(log.novel_id),
                    "chapter_id": log.chapter_id,
                    "chapter_number": chapters[log.chapter_id].number if log.chapter_id in chapters else None,
                    "chapter_title": chapters[log.chapter_id].title if log.chapter_id in chapters else None,
                    "shot_id": log.shot_id,
                    "shot_index": shot_indexes.get(log.shot_id),
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


def _usage_number(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def _new_usage_node(id_, label):
    return {"id": id_, "label": label, "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "call_count": 0, "missing_usage_count": 0,
            "partial_usage_count": 0}


def _chapter_usage_label(chapter):
    title = (chapter.title or "").strip()
    return title if re.match(r"^第.{1,10}章", title) else f"第{chapter.number}章 · {title}"


def _add_usage(node, metrics):
    node["call_count"] += 1
    values = metrics if isinstance(metrics, dict) else {}
    input_tokens = _usage_number(values.get("input_tokens"))
    output_tokens = _usage_number(values.get("output_tokens"))
    total_tokens = _usage_number(values.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    if input_tokens is not None:
        node["input_tokens"] += input_tokens
    if output_tokens is not None:
        node["output_tokens"] += output_tokens
    if total_tokens is not None:
        node["total_tokens"] += total_tokens
        if input_tokens is None or output_tokens is None:
            node["partial_usage_count"] += 1
    else:
        node["missing_usage_count"] += 1


@router.get("/token-usage/hierarchy")
def get_llm_token_usage_hierarchy(db: Session = Depends(get_db)):
    """Aggregate provider-reported tokens across all saved LLM logs by novel/chapter/Shot."""
    novels = dict(db.query(Novel.id, Novel.title).all())
    chapters = {row.id: row for row in db.query(Chapter.id, Chapter.novel_id, Chapter.number, Chapter.title).all()}
    shots = {row.id: row for row in db.query(Shot.id, Shot.chapter_id, Shot.index).all()}
    root = _new_usage_node(None, "全部调用")
    novel_nodes = {}
    for novel_id, chapter_id, shot_id, metrics in db.query(
        LLMLog.novel_id, LLMLog.chapter_id, LLMLog.shot_id, LLMLog.usage_metrics
    ).yield_per(500):
        if shot_id in shots:
            chapter_id = shots[shot_id].chapter_id
        if chapter_id in chapters:
            novel_id = chapters[chapter_id].novel_id
        novel_node = novel_nodes.setdefault(novel_id, {**_new_usage_node(
            novel_id, novels.get(novel_id, f"已删除小说 · {novel_id}") if novel_id else "未归属小说"
        ), "chapters": {}})
        chapter_node = novel_node["chapters"].setdefault(chapter_id, {**_new_usage_node(
            chapter_id,
            _chapter_usage_label(chapters[chapter_id]) if chapter_id in chapters else
            (f"已删除章回 · {chapter_id}" if chapter_id else "未归属章回")
        ), "shots": {}})
        shot_node = chapter_node["shots"].setdefault(shot_id, _new_usage_node(
            shot_id, f"Shot {shots[shot_id].index}" if shot_id in shots else
            (f"已删除 Shot · {shot_id}" if shot_id else "未归属 Shot")
        ))
        for node in (root, novel_node, chapter_node, shot_node):
            _add_usage(node, metrics)
    result = []
    for novel_id, novel_node in sorted(novel_nodes.items(), key=lambda item: (item[0] is None, item[1]["label"])):
        chapter_items = list(novel_node.pop("chapters").items())
        novel_node["chapters"] = []
        for chapter_id, chapter_node in sorted(chapter_items, key=lambda item: (
            item[0] is None, chapters[item[0]].number if item[0] in chapters else 10**9
        )):
            shot_items = list(chapter_node.pop("shots").items())
            chapter_node["shots"] = [node for _, node in sorted(shot_items, key=lambda item: (
                item[0] is None, shots[item[0]].index if item[0] in shots else 10**9
            ))]
            novel_node["chapters"].append(chapter_node)
        result.append(novel_node)
    root["novels"] = result
    return {"success": True, "data": root}


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
    llmlog_repo: LLMLogRepository = Depends(get_llmlog_repo),
    db: Session = Depends(get_db),
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
            "image_inputs": log_image_inputs(log.request_info),
            "response": log.response,
            "status": log.status,
            "error_message": log.error_message,
            "task_type": log.task_type,
            "novel_id": log.novel_id,
            "novel_title": db.query(Novel.title).filter(Novel.id == log.novel_id).scalar() if log.novel_id else None,
            "chapter_id": log.chapter_id,
            "chapter_number": db.query(Chapter.number).filter(Chapter.id == log.chapter_id).scalar() if log.chapter_id else None,
            "chapter_title": db.query(Chapter.title).filter(Chapter.id == log.chapter_id).scalar() if log.chapter_id else None,
            "shot_id": log.shot_id,
            "shot_index": db.query(Shot.index).filter(Shot.id == log.shot_id).scalar() if log.shot_id else None,
            "character_id": log.character_id,
            "used_proxy": log.used_proxy,
            "duration": log.duration,
            "metrics": log.usage_metrics,
        }
    }
