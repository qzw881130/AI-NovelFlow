"""
任务 API 路由

只负责请求/响应处理，业务逻辑委托给 TaskService
"""
import gzip
import json
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import case, func
from sqlalchemy.orm import Session, load_only
from typing import Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.workflow import Workflow
from app.models.task import Task
from app.repositories import TaskRepository
from app.services.task_service import TaskService
from app.services.task_workflow_archive import build_workflow_archive
from starlette.concurrency import run_in_threadpool
from app.api.deps import get_task_repo

router = APIRouter()


def _task_read_response(data: dict, request: Request, *, db_ms: float, projection_ms: float) -> Response:
    started = perf_counter()
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Vary": "Accept-Encoding"}
    if "gzip" in request.headers.get("accept-encoding", "").lower():
        body = gzip.compress(body, compresslevel=3, mtime=0)
        headers["Content-Encoding"] = "gzip"
    headers["Server-Timing"] = (
        f"db;dur={db_ms:.2f}, projection;dur={projection_ms:.2f}, "
        f"serialize;dur={(perf_counter() - started) * 1000:.2f}"
    )
    return Response(content=body, media_type="application/json", headers=headers)


def _json_value(value):
    if not value:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _task_summary_query(db: Session, *, status_only: bool):
    """Select status columns without materializing workflow, prompt or metadata blobs."""
    columns = [
        Task.id, Task.type, Task.status, Task.name, Task.progress, Task.current_step,
        Task.result_url, Task.error_message, Task.shot_id, Task.chapter_id,
        Task.novel_id, Task.parent_task_id, Task.source_task_id, Task.batch_order,
        Task.clip_index,
        Task.comfyui_prompt_id, Task.created_at, Task.started_at,
        Task.completed_at, Task.updated_at,
    ]
    safe_metadata = case(
        (func.json_valid(Task.metadata_json) == 1, Task.metadata_json), else_="{}"
    )
    # Even lightweight polling must distinguish candidates from official output.
    columns.append(func.coalesce(func.json_extract(safe_metadata, "$.result_mode"), "APPLY").label("result_mode"))
    columns.append(func.json_extract(safe_metadata, "$.grid_step").label("grid_step"))
    columns.append(func.json_extract(safe_metadata, "$.panel_index").label("grid_panel_index"))
    columns.append(func.json_extract(safe_metadata, "$.shot_results").label("grid_auto_shot_results"))
    if not status_only:
        for key in (
            "candidate_result", "source_revision", "source_clip_plan_fingerprint",
            "execution_scope", "clip_id", "clip_index", "clip_plan_revision", "h3_prompt_pipeline", "video_prompt_language", "generation_quality_warnings",
            "approval_status", "approval_mode", "artifact_kind", "capability",
            "planned_duration", "actual_duration", "assembled_media_duration",
            "assembled_result", "physical_output", "clip_playback",
            "dialogue_assignment", "previous_approved_task_id",
            "previous_approved_video_url", "previous_approved_video_source",
            "comfyui_error",
            "continuation_mode", "planned_capability", "effective_capability",
            "execution_projection", "suppressed_temporal_anchor_ids",
            "execution_contract.capability", "execution_contract.artifact_kind",
            "execution_contract.previous_clip", "execution_contract.temporal_anchor_manifest.anchors",
            "nameplate_preview_url", "nameplate_status", "nameplate_warnings", "nameplate_auto_approved",
        ):
            columns.append(func.json_extract(safe_metadata, f"$.{key}").label(key.replace(".", "__")))
        columns.append(func.json_array_length(safe_metadata, "$.video_reference_manifest.references").label("ordinary_reference_count"))
    return db.query(*columns)


def _format_task_summaries(rows, *, status_only: bool) -> list[dict]:
    from app.utils.time_utils import format_datetime

    result = []
    for row in rows:
        value = row._mapping
        task = {
            "id": value["id"], "type": value["type"], "status": value["status"], "resultMode": value["result_mode"],
            "name": value["name"], "progress": value["progress"],
            "currentStep": value["current_step"], "resultUrl": value["result_url"],
            "errorMessage": value["error_message"], "shotId": value["shot_id"],
            "chapterId": value["chapter_id"], "novelId": value["novel_id"],
            "parentTaskId": value["parent_task_id"], "sourceTaskId": value["source_task_id"],
            "batchOrder": value["batch_order"], "clipIndex": value["clip_index"],
            "gridStep": value["grid_step"], "panelIndex": value["grid_panel_index"],
            "autoShotResults": _json_value(value["grid_auto_shot_results"]) if value["type"] in {"grid_auto_batch", "grid_board_batch"} else None,
            "comfyuiPromptId": value["comfyui_prompt_id"],
            "createdAt": format_datetime(value["created_at"]),
            "startedAt": format_datetime(value["started_at"]),
            "completedAt": format_datetime(value["completed_at"]),
        }
        if not status_only:
            if task["type"] in {"chapter_video", "grid_chapter_merge"}:
                task["nameplatePreview"] = {
                    "url": value["nameplate_preview_url"],
                    "status": value["nameplate_status"],
                    "warnings": _json_value(value["nameplate_warnings"]) or [],
                    "autoApproved": bool(value["nameplate_auto_approved"]),
                }
            execution = {key: value[key] for key in (
                "result_mode", "source_revision", "source_clip_plan_fingerprint",
                "execution_scope", "clip_id", "clip_index", "clip_plan_revision", "h3_prompt_pipeline", "video_prompt_language",
                "approval_status", "approval_mode", "artifact_kind", "capability",
                "planned_duration", "actual_duration", "assembled_media_duration",
                "previous_approved_task_id", "previous_approved_video_url",
                "previous_approved_video_source",
                "continuation_mode", "planned_capability", "effective_capability",
            ) if value[key] is not None}
            for key in ("candidate_result", "assembled_result", "physical_output", "clip_playback", "dialogue_assignment", "generation_quality_warnings",
                        "execution_projection", "suppressed_temporal_anchor_ids"):
                if value[key] is not None:
                    execution[key] = _json_value(value[key])
            previous_clip = _json_value(value["execution_contract__previous_clip"])
            anchors = _json_value(value["execution_contract__temporal_anchor_manifest__anchors"])
            if previous_clip is not None or anchors is not None or value["execution_contract__capability"] is not None:
                execution["execution_contract"] = {
                    "capability": value["execution_contract__capability"],
                    "artifact_kind": value["execution_contract__artifact_kind"],
                    **({"previous_clip": previous_clip} if previous_clip is not None else {}),
                    **({"temporal_anchor_manifest": {"anchors": anchors}} if anchors is not None else {}),
                }
            if value["ordinary_reference_count"] is not None:
                task["ordinaryReferenceCount"] = value["ordinary_reference_count"]
            task["clipExecution"] = execution if execution.get("execution_scope") == "CLIP" else None
            error = _json_value(value["comfyui_error"])
            if isinstance(error, dict) and error.get("error_code"):
                from app.services.comfyui.errors import error_payload
                task["comfyuiError"] = error_payload(
                    error["error_code"], error.get("stage"), error.get("effective_url"),
                    error.get("underlying_error"), http_status=error.get("http_status"),
                    attempts=error.get("attempts", 0), prompt_submitted=error.get("prompt_submitted", False),
                    configured_url=error.get("configured_url"),
                )
        result.append(task)
    return result

IMAGE_TASK_TYPES = {
    "character_portrait", "scene_image", "prop_image", "shot_image", "shot_image_repair_candidate", "shot_image_repair",
    "keyframe_image", "single_image_edit",
}


def _extract_character_prompt_items(task, workflow_obj: dict, node_mapping: dict) -> list[dict]:
    if task.type != "character_portrait" or not isinstance(workflow_obj, dict):
        return []

    mapped_roles = {
        str(node_mapping.get("appearance_node_id")): ("appearance", "人物外貌") if node_mapping.get("appearance_node_id") else None,
        str(node_mapping.get("style_node_id")): ("style", "视觉风格") if node_mapping.get("style_node_id") else None,
    }
    mapped_roles = {node_id: role for node_id, role in mapped_roles.items() if role}
    items = []
    role_order = {"layout": 0, "style": 1, "appearance": 2}

    for node_id, node in workflow_obj.items():
        if not isinstance(node, dict) or node.get("class_type") != "CR Prompt Text":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        content = next((inputs.get(key) for key in ("prompt", "text", "value") if isinstance(inputs.get(key), str) and inputs.get(key).strip()), None)
        if not content:
            continue
        title = str(node.get("_meta", {}).get("title") or node.get("class_type") or node_id)
        mapped = mapped_roles.get(str(node_id))
        title_lower = title.lower()
        if mapped:
            role, label = mapped
        elif any(keyword in title_lower for keyword in ("人物形象", "外貌", "appearance", "character appearance")):
            role, label = "appearance", "人物外貌"
        elif title_lower.strip() == "style" or title_lower.endswith(" style") or "#490 style" in title_lower:
            role, label = "style", "视觉风格"
        elif any(keyword in title_lower for keyword in ("四视图", "布局", "turnaround", "reference sheet")):
            role, label = "layout", "角色图布局"
        else:
            continue
        items.append({
            "nodeId": str(node_id),
            "role": role,
            "label": label,
            "nodeTitle": title,
            "content": content,
        })

    return sorted(items, key=lambda item: (role_order[item["role"]], item["nodeId"]))


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    """获取 TaskService 实例"""
    return TaskService(db)


# ==================== 任务列表 ====================

@router.get("/", response_model=dict)
def list_tasks(
        request: Request,
        status: Optional[str] = None,
        type: Optional[str] = None,
        chapter_id: Optional[str] = None,
        shot_id: Optional[str] = None,
        active_only: bool = False,
        summary: bool = False,
        status_only: bool = False,
        limit: int = 50,
        db: Session = Depends(get_db),
        task_repo: TaskRepository = Depends(get_task_repo)
):
    """获取任务列表"""
    started = perf_counter()
    if summary or status_only:
        query = _task_summary_query(db, status_only=status_only)
        if chapter_id:
            query = query.filter(Task.chapter_id == chapter_id)
        if type:
            query = query.filter(Task.type == type)
        if status:
            query = query.filter(Task.status == status)
        if shot_id:
            query = query.filter(Task.shot_id == shot_id)
        if active_only:
            query = query.filter(Task.status.in_(["pending", "queued", "running", "processing"]))
        query = query.order_by(Task.created_at.desc())
        if active_only or not chapter_id:
            query = query.limit(max(1, min(limit, 1000)))
        rows = query.all()
        db_ms = (perf_counter() - started) * 1000
        projected = perf_counter()
        data = _format_task_summaries(rows, status_only=status_only)
        return _task_read_response({"success": True, "data": data}, request,
                                   db_ms=db_ms, projection_ms=(perf_counter() - projected) * 1000)

    if chapter_id or active_only:
        # Page initialization reads several task kinds concurrently. Filter in SQL
        # before loading large historical workflows/metadata for unrelated tasks.
        query = db.query(Task)
        if chapter_id:
            query = query.filter(Task.chapter_id == chapter_id)
        if type:
            query = query.filter(Task.type == type)
        if status:
            query = query.filter(Task.status == status)
        if shot_id:
            query = query.filter(Task.shot_id == shot_id)
        if active_only:
            query = query.filter(Task.status.in_(["pending", "queued", "running", "processing"]))
            tasks = query.order_by(Task.created_at.desc()).limit(max(1, min(limit, 50))).all()
        else:
            tasks = query.order_by(Task.created_at.desc()).all()
    else:
        tasks = task_repo.list_by_filters(status=status, task_type=type, limit=limit)

    # The background reconciliation loop owns ComfyUI recovery. List reads must
    # not wait for remote queue/history calls or repeat them for every browser.
    db_ms = (perf_counter() - started) * 1000
    projected = perf_counter()
    data = _format_task_rows(tasks, db)
    return _task_read_response({"success": True, "data": data}, request,
                               db_ms=db_ms, projection_ms=(perf_counter() - projected) * 1000)


def _format_task_rows(tasks: list, db: Session) -> list:
    # 获取所有需要的小说、章节和工作流信息
    novel_ids = {t.novel_id for t in tasks if t.novel_id}
    chapter_ids = {t.chapter_id for t in tasks if t.chapter_id}
    workflow_ids = {t.workflow_id for t in tasks if t.workflow_id}
    shot_ids = {t.shot_id for t in tasks if t.type == "shot_video" and t.shot_id}

    novels = {n.id: n for n in db.query(Novel).options(load_only(Novel.id, Novel.title)).filter(Novel.id.in_(novel_ids)).all()} if novel_ids else {}
    chapters = {c.id: c for c in db.query(Chapter).options(load_only(Chapter.id, Chapter.number, Chapter.title)).filter(Chapter.id.in_(chapter_ids)).all()} if chapter_ids else {}
    workflows = {w.id: w for w in db.query(Workflow).options(load_only(Workflow.id, Workflow.is_system)).filter(Workflow.id.in_(workflow_ids)).all()} if workflow_ids else {}
    shots = {s.id: s for s in db.query(Shot).options(load_only(Shot.id, Shot.video_director_plan)).filter(Shot.id.in_(shot_ids)).all()} if shot_ids else {}

    return TaskService.format_task_list(tasks, novels, chapters, workflows, shots=shots)


@router.get("/page", response_model=dict)
def list_tasks_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    status: Optional[str] = None,
    type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Read only the displayed page; count/filter history in SQL, off the event loop."""
    query = db.query(Task)
    if type:
        query = query.filter(Task.type == type)
    counts = dict(query.with_entities(Task.status, func.count(Task.id)).group_by(Task.status).all())
    stats = {key: counts.get(key, 0) for key in ("pending", "running", "completed", "failed", "cancelled")}
    stats["pending"] += counts.get("queued", 0)
    stats["all"] = sum(counts.values())
    if status:
        query = query.filter(Task.status.in_(["pending", "queued"]) if status == "pending" else Task.status == status)
    total = query.count() if status else stats["all"]
    # Retried tasks keep their original id and created_at. Order the task page by
    # recent activity so a Clip completed by a new batch remains visible.
    tasks = query.order_by(
        func.coalesce(Task.updated_at, Task.created_at).desc(), Task.id.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "success": True,
        "data": {
            "items": _format_task_rows(tasks, db),
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "stats": stats,
            "types": [value for (value,) in db.query(Task.type).distinct().order_by(Task.type).all() if value],
        },
    }


@router.get("/{task_id}", response_model=dict)
async def get_task(task_id: str, request: Request, summary: bool = False, references_only: bool = False,
                   db: Session = Depends(get_db), task_repo: TaskRepository = Depends(get_task_repo)):
    """获取任务详情"""
    started = perf_counter()
    if references_only:
        row = db.query(Task.id, Task.status, Task.reference_images).filter(Task.id == task_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        db_ms = (perf_counter() - started) * 1000
        projected = perf_counter()
        images = _json_value(row.reference_images)
        return _task_read_response({"success": True, "data": {
            "id": row.id, "status": row.status,
            "referenceImages": images if isinstance(images, list) else [],
        }}, request, db_ms=db_ms, projection_ms=(perf_counter() - projected) * 1000)
    if summary:
        row = _task_summary_query(db, status_only=False).filter(Task.id == task_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        db_ms = (perf_counter() - started) * 1000
        projected = perf_counter()
        data = _format_task_summaries([row], status_only=False)[0]
        return _task_read_response({"success": True, "data": data}, request,
                                   db_ms=db_ms, projection_ms=(perf_counter() - projected) * 1000)
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    db_ms = (perf_counter() - started) * 1000
    projected = perf_counter()
    data = TaskService.format_task_detail(task)
    return _task_read_response({"success": True, "data": data}, request,
                               db_ms=db_ms, projection_ms=(perf_counter() - projected) * 1000)


# ==================== 任务操作 ====================


class CompletedClipReceiptAcceptance(BaseModel):
    expected_prompt_id: str
    clip_plan_revision: int


@router.post("/{task_id}/accept-completed-clip", response_model=dict)
async def accept_completed_clip_receipt(
    task_id: str,
    request: CompletedClipReceiptAcceptance,
    task_service: TaskService = Depends(get_task_service),
):
    """Accept one completed C1 receipt while retaining the cancelled attempt."""
    from app.services.clip_result_recovery import accept_cancelled_generate_receipt
    from app.services.canonical_execution_invalidation import CanonicalExecutionConflict

    source = task_service.db.get(Task, task_id)
    if not source:
        raise HTTPException(status_code=404, detail="原任务不存在")
    try:
        recovered = await accept_cancelled_generate_receipt(
            source, request.expected_prompt_id, request.clip_plan_revision,
            task_service.db, task_service.comfyui_service,
        )
    except (CanonicalExecutionConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"success": True, "data": {"taskId": recovered.id, "sourceTaskId": source.id,
                                      "status": recovered.status, "videoUrl": recovered.result_url}}

@router.post("/{task_id}/cancel", response_model=dict)
async def cancel_task(
    task_id: str,
    task_service: TaskService = Depends(get_task_service),
):
    """取消任务但保留任务记录。"""
    cancel_result = await task_service.cancel_task(task_id)
    if cancel_result.get("status_code"):
        raise HTTPException(status_code=cancel_result["status_code"], detail=cancel_result.get("message"))
    return {
        "success": True,
        "message": cancel_result.get("message") or "任务已取消",
        "details": cancel_result.get("details"),
    }


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    task_service: TaskService = Depends(get_task_service),
    task_repo: TaskRepository = Depends(get_task_repo),
):
    """删除任务"""
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status in ["pending", "queued", "running"]:
        cancel_result = await task_service.cancel_task(task_id)
        if cancel_result.get("status_code"):
            raise HTTPException(status_code=cancel_result["status_code"], detail=cancel_result.get("message"))
        task = cancel_result.get("task") or task_repo.get_by_id(task_id)

    task_repo.delete(task)

    return {"success": True, "message": "任务已删除"}


@router.post("/cancel-all/", response_model=dict)
async def cancel_all_tasks(
    task_service: TaskService = Depends(get_task_service)
):
    """
    终止所有正在进行或待处理的任务
    
    执行顺序：
    1. 先清空 ComfyUI 队列（清除所有等待中的任务）
    2. 再中断当前正在执行的任务
    """
    return await task_service.cancel_all_tasks()


@router.post("/{task_id}/retry")
async def retry_task(
        task_id: str,
        task_service: TaskService = Depends(get_task_service)
):
    """重试失败的任务"""
    result = task_service.retry_task(task_id)
    
    if result.get("status_code"):
        raise HTTPException(status_code=result["status_code"], detail=result.get("message"))
    
    return result


# ==================== 任务工作流 ====================

@router.get("/{task_id}/workflow", response_model=dict)
async def get_task_workflow(
    task_id: str, 
    task_repo: TaskRepository = Depends(get_task_repo),
    db: Session = Depends(get_db),
):
    """获取任务提交给ComfyUI的工作流JSON"""
    import json
    from app.utils.workflow_seed import extract_workflow_seed
    
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        metadata = json.loads(task.metadata_json or "{}")
        metadata = metadata if isinstance(metadata, dict) else {}
    except (ValueError, TypeError):
        metadata = {}
    execution_duration = {key: metadata.get(key) for key in (
        "planned_duration", "original_duration", "optimized_duration", "effective_duration", "actual_duration",
        "duration_delta", "actual_duration_delta", "duration_source",
    )}
    try:
        reference_images = json.loads(task.reference_images or "[]")
        reference_images = reference_images if isinstance(reference_images, list) else []
    except (ValueError, TypeError):
        reference_images = []
    reference_video = metadata.get("previous_approved_video_url")
    result_image = task.result_url if task.type in IMAGE_TASK_TYPES and task.status == "completed" else None
    prompt_text = task.prompt_text
    if not prompt_text and task.type == "chapter_background_music":
        from app.services.background_music_service import format_background_music_prompt
        prompt_text = format_background_music_prompt(metadata)

    # 如果任务保存了工作流JSON，直接返回
    if task.workflow_json:
        try:
            workflow_obj = json.loads(task.workflow_json)
            workflow = db.query(Workflow).filter(Workflow.id == task.workflow_id).first() if task.workflow_id else None
            try:
                node_mapping = json.loads(workflow.node_mapping or "{}") if workflow else {}
            except Exception:
                node_mapping = {}
            return {
                "success": True,
                "data": {
                    "workflow": workflow_obj,
                    "nodeMapping": node_mapping,
                    "seed": task.seed or extract_workflow_seed(workflow_obj),
                    "prompt": prompt_text or "未保存提示词",
                    "promptItems": _extract_character_prompt_items(task, workflow_obj, node_mapping),
                    "executionDuration": execution_duration,
                    "referenceImages": reference_images,
                    "referenceVideo": reference_video,
                    "resultImage": result_image,
                }
            }
        except Exception as e:
            return {
                "success": True,
                "data": {
                    "workflow": task.workflow_json,
                    "nodeMapping": {},
                    "seed": task.seed or extract_workflow_seed(task.workflow_json),
                    "prompt": prompt_text or "未保存提示词",
                    "promptItems": [],
                    "executionDuration": execution_duration,
                    "referenceImages": reference_images,
                    "referenceVideo": reference_video,
                    "resultImage": result_image,
                }
            }

    # 没有保存实际提交的工作流，返回空
    return {
        "success": True,
        "data": {
            "workflow": None,
            "nodeMapping": {},
            "seed": task.seed,
            "prompt": prompt_text or "未保存提示词",
            "promptItems": [],
            "executionDuration": execution_duration,
            "referenceImages": reference_images,
            "referenceVideo": reference_video,
            "resultImage": result_image,
            "note": "工作流尚未提交到ComfyUI或执行未完成，请稍后查看"
        }
    }


@router.get("/{task_id}/workflow/archive")
async def download_task_workflow_archive(
    task_id: str,
    task_repo: TaskRepository = Depends(get_task_repo),
    db: Session = Depends(get_db),
):
    """Download the submitted workflow and its local image/video references."""
    result = await get_task_workflow(task_id, task_repo=task_repo, db=db)
    return await run_in_threadpool(build_workflow_archive, task_id, result["data"])


@router.get("/{task_id}/clips/{window_index}/workflow", response_model=dict)
async def get_task_clip_workflow(
    task_id: str,
    window_index: int,
    db: Session = Depends(get_db),
    task_repo: TaskRepository = Depends(get_task_repo),
):
    """获取多 Clip 视频任务中单个 Clip 实际提交的工作流JSON。"""
    import json
    from app.utils.workflow_seed import extract_workflow_seed

    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.type not in {"shot_video", "shot_video_hd"} or not task.shot_id:
        raise HTTPException(status_code=400, detail="该任务不是分镜视频任务")

    window_plans = []
    if task.video_director_clips:
        try:
            parsed = json.loads(task.video_director_clips)
            window_plans = parsed if isinstance(parsed, list) else []
        except Exception:
            raise HTTPException(status_code=400, detail="任务 Clip 快照格式无效")
    if not window_plans:
        shot = db.query(Shot).filter(Shot.id == task.shot_id).first()
        if not shot or not shot.video_director_plan:
            raise HTTPException(status_code=404, detail="未找到分镜视频导演计划")

        try:
            plan = json.loads(shot.video_director_plan)
        except Exception:
            raise HTTPException(status_code=400, detail="分镜视频导演计划格式无效")

        window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
    clip = next((window for window in window_plans if isinstance(window, dict) and int(window.get("window_index") or 0) == window_index), None)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip 不存在")

    workflow_id = clip.get("workflow_id") or task.workflow_id
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first() if workflow_id else None
    try:
        node_mapping = json.loads(workflow.node_mapping or "{}") if workflow else {}
    except Exception:
        node_mapping = {}

    workflow_json = clip.get("workflow_json") or clip.get("replay_workflow_json") or clip.get("source_workflow_json")
    if not workflow_json and clip.get("prompt_id"):
        prompt_state = await TaskService(db).comfyui_service.client.get_prompt_state(str(clip.get("prompt_id")))
        prompt_history = prompt_state.get("history") if prompt_state.get("state") in {"history", "completed"} else None
        prompt_payload = prompt_history.get("prompt") if isinstance(prompt_history, dict) else None
        if isinstance(prompt_payload, list) and len(prompt_payload) > 2 and isinstance(prompt_payload[2], dict):
            workflow_json = prompt_payload[2]
            clip["workflow_json"] = workflow_json
            task.video_director_clips = json.dumps(window_plans, ensure_ascii=False)

            shot = db.query(Shot).filter(Shot.id == task.shot_id).first()
            if shot and shot.video_director_plan:
                try:
                    plan = json.loads(shot.video_director_plan)
                    plan_windows = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
                    for plan_window in plan_windows:
                        if isinstance(plan_window, dict) and int(plan_window.get("window_index") or 0) == window_index:
                            plan_window["workflow_json"] = workflow_json
                            break
                    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
                except Exception:
                    pass
            db.commit()

    try:
        task_metadata = json.loads(task.metadata_json or "{}")
        task_metadata = task_metadata if isinstance(task_metadata, dict) else {}
    except (ValueError, TypeError):
        task_metadata = {}
    reference_video = clip.get("previous_approved_video_url")
    if not reference_video and str(task_metadata.get("clip_index")) == str(window_index):
        reference_video = task_metadata.get("previous_approved_video_url")

    return {
        "success": True,
        "data": {
            "workflow": workflow_json,
            "nodeMapping": node_mapping,
            "seed": clip.get("seed") or extract_workflow_seed(workflow_json),
            "prompt": clip.get("execution_prompt_text") or clip.get("prompt_text") or "未保存提示词",
            "executionDuration": clip.get("h3_execution"),
            "referenceImages": clip.get("reference_images") if isinstance(clip.get("reference_images"), list) else [],
            "referenceVideo": reference_video,
            "windowIndex": window_index,
            "note": None if clip.get("workflow_json") else "该 Clip 尚未保存实际提交的工作流 JSON",
        }
    }


@router.get("/{task_id}/clips/{window_index}/workflow/archive")
async def download_task_clip_workflow_archive(
    task_id: str,
    window_index: int,
    task_repo: TaskRepository = Depends(get_task_repo),
    db: Session = Depends(get_db),
):
    """Download the selected Clip workflow and its own references."""
    result = await get_task_clip_workflow(task_id, window_index, db=db, task_repo=task_repo)
    return await run_in_threadpool(build_workflow_archive, task_id, result["data"])
