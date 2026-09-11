"""
任务 API 路由

只负责请求/响应处理，业务逻辑委托给 TaskService
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.workflow import Workflow
from app.repositories import TaskRepository
from app.services.task_service import TaskService
from app.services.shot_video_execution import has_video_execution
from app.services.task_execution import ExecutionConflict
from app.api.deps import get_task_repo

router = APIRouter()


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    """获取 TaskService 实例"""
    return TaskService(db)


# ==================== 任务列表 ====================

@router.get("/", response_model=dict)
async def list_tasks(
        status: Optional[str] = None,
        type: Optional[str] = None,
        chapter_id: Optional[str] = None,
        limit: int = 50,
        db: Session = Depends(get_db),
        task_repo: TaskRepository = Depends(get_task_repo),
        task_service: TaskService = Depends(get_task_service)
):
    """获取任务列表"""
    if chapter_id:
        # 按章节筛选
        tasks = task_repo.get_by_chapter(chapter_id)
        # 额外筛选类型和状态
        if type:
            tasks = [t for t in tasks if t.type == type]
        if status:
            tasks = [t for t in tasks if t.status == status]
        tasks = tasks[:limit]
    else:
        tasks = task_repo.list_by_filters(status=status, task_type=type, limit=limit)

    if any(t.status in ["pending", "queued", "running"] for t in tasks):
        updated_count = await task_service.reconcile_active_tasks(tasks, db=db)
        if updated_count:
            if chapter_id:
                tasks = task_repo.get_by_chapter(chapter_id)
                if type:
                    tasks = [t for t in tasks if t.type == type]
                if status:
                    tasks = [t for t in tasks if t.status == status]
                tasks = tasks[:limit]
            else:
                tasks = task_repo.list_by_filters(status=status, task_type=type, limit=limit)

    # 获取所有需要的小说、章节和工作流信息
    novel_ids = {t.novel_id for t in tasks if t.novel_id}
    chapter_ids = {t.chapter_id for t in tasks if t.chapter_id}
    workflow_ids = {t.workflow_id for t in tasks if t.workflow_id}
    shot_ids = {t.shot_id for t in tasks if t.type == "shot_video" and t.shot_id}

    novels = {n.id: n for n in db.query(Novel).filter(Novel.id.in_(novel_ids)).all()} if novel_ids else {}
    chapters = {c.id: c for c in db.query(Chapter).filter(Chapter.id.in_(chapter_ids)).all()} if chapter_ids else {}
    workflows = {w.id: w for w in
                 db.query(Workflow).filter(Workflow.id.in_(workflow_ids)).all()} if workflow_ids else {}
    shots = {s.id: s for s in db.query(Shot).filter(Shot.id.in_(shot_ids)).all()} if shot_ids else {}

    return {
        "success": True,
        "data": TaskService.format_task_list(tasks, novels, chapters, workflows, shots=shots)
    }


@router.get("/{task_id}", response_model=dict)
async def get_task(task_id: str, task_repo: TaskRepository = Depends(get_task_repo)):
    """获取任务详情"""
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "success": True,
        "data": TaskService.format_task_detail(task)
    }


# ==================== 任务操作 ====================

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

    try:
        if TaskService.cancellation_state(task) in {"pending", "unknown"}:
            raise ExecutionConflict("REMOTE_CANCELLATION_UNCONFIRMED")
    except ExecutionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    expected = TaskService._task_snapshot(task)
    if task.status in ["pending", "queued", "running"]:
        cancel_result = await task_service.cancel_task(task_id)
        if not cancel_result.get("success") or cancel_result.get("status_code"):
            raise HTTPException(status_code=cancel_result.get("status_code") or 409, detail=cancel_result.get("message"))
        if any(item.get("remote_unconfirmed") for item in cancel_result.get("details", {}).get("tasks", [])):
            raise HTTPException(status_code=409, detail="本地任务已取消，但远程执行尚未确认终止；已保留任务证据")
        expected = cancel_result.get("terminal_snapshot")

    if not expected or expected.get("id") != task_id or expected.get("status") not in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="任务尚未稳定终止，不能删除")
    from types import SimpleNamespace
    try:
        if TaskService.cancellation_state(SimpleNamespace(**expected)) in {"pending", "unknown"}:
            raise ExecutionConflict("REMOTE_CANCELLATION_UNCONFIRMED")
    except ExecutionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    from app.models.task import Task
    from sqlalchemy.orm import aliased
    db = task_repo.db
    child = aliased(Task)
    with db.no_autoflush:
        count = db.query(Task).filter(*[
            getattr(Task, key) == value for key, value in expected.items()
        ], ~db.query(child.id).filter(child.parent_task_id == task_id,
                                     child.status.in_(["pending", "queued", "running"])).exists()).delete(synchronize_session=False)
        if count != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="任务或子任务执行证据已更改，未删除；请刷新后重试")
        db.commit()

    return {"success": True, "message": "任务已删除"}


@router.post("/cancel-all/", response_model=dict)
async def cancel_all_tasks(
    task_service: TaskService = Depends(get_task_service)
):
    """先保存本地终态，再按任务保存的端点取消对应远程任务。"""
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
    task_repo: TaskRepository = Depends(get_task_repo)
):
    """获取任务提交给ComfyUI的工作流JSON"""
    import json
    
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    purpose = {**TaskService.format_execution_purpose(task), **TaskService.format_video_execution(task)}
    if task.type == "keyframe_image":
        from app.services.keyframe_reference_contract import (
            CONTRACT_KEY, OBSERVATIONS_KEY, KeyframeReferenceError, digest,
            assert_keyframe_graph_matches, json_value, read_contract, validate_frozen_contract,
        )

        proof_error = None
        try:
            metadata = json_value(task.metadata_json, dict)
            has_contract = CONTRACT_KEY in metadata
        except KeyframeReferenceError as exc:
            metadata, has_contract, proof_error = {}, True, exc
        if has_contract:
            raw_contract = metadata.get(CONTRACT_KEY)
            contract = raw_contract if isinstance(raw_contract, dict) else {}
            submit = contract.get("submit") if isinstance(contract.get("submit"), dict) else {}
            prompt = contract.get("prompt") if isinstance(contract.get("prompt"), dict) else {}
            target = contract.get("target") if isinstance(contract.get("target"), dict) else {}
            workflow_obj = contract.get("prepared_workflow")
            workflow_source, verified = "unverified", False
            acknowledged = submit.get("state") == "submitted" or submit.get("prompt_id") is not None
            try:
                if task.workflow_json:
                    workflow_obj = None
                    parsed = json.loads(task.workflow_json)
                    if not isinstance(parsed, dict):
                        raise KeyframeReferenceError("INVALID_SAVED_JSON_TYPE", "workflow_json")
                    digest(parsed)
                    workflow_obj = parsed
                if proof_error:
                    raise proof_error
                saved = read_contract(task)
                if saved is None:
                    raise KeyframeReferenceError("CONTRACT_PROOF_INVALID", "unsupported contract record")
                validate_frozen_contract(saved, task, require_submitted=acknowledged)
                if acknowledged:
                    if not task.workflow_json or not isinstance(workflow_obj, dict):
                        raise KeyframeReferenceError("TASK_PROJECTION_CHANGED", "workflow_json")
                    assert_keyframe_graph_matches(workflow_obj, saved, code="TASK_PROJECTION_CHANGED")
                    workflow_source = "submitted"
                else:
                    workflow_source = "prepared"
                verified = True
            except (KeyframeReferenceError, ValueError, TypeError) as exc:
                proof_error = exc
                if (workflow_obj is None and not task.workflow_json and not acknowledged
                        and isinstance(contract.get("phase"), str)
                        and contract.get("phase") in {"planned", "resolved", "frozen", "prompt_building"}
                        and getattr(exc, "code", None) in {"REFERENCE_NOT_BOUND", "CONTRACT_PROOF_INVALID"}):
                    workflow_source = None
            try:
                reference_images = [image for image in json_value(task.reference_images, list)
                                    if isinstance(image, dict) and isinstance(image.get("label"), str)
                                    and isinstance(image.get("url"), str)]
            except KeyframeReferenceError:
                reference_images = []
            summary = {key: contract[key] for key in (
                "version", "attempt_id", "storage_revision", "storage_hash", "phase", "endpoint", "planned", "workflow", "resolved",
                "binding", "manifest", "fallback", "frozen_binding_hash", "submit", "result", "failure",
            ) if key in contract}
            summary["target"] = {key: target.get(key) for key in (
                "shot_id", "chapter_id", "frame_index", "plan_keyframe_index",
            )}
            summary["prompt"] = {key: value for key, value in prompt.items()
                                 if key in {"origin", "llm_invoked", "text_hash", "cache_fingerprint", "validation"}}
            projected_metadata = {CONTRACT_KEY: summary}
            if OBSERVATIONS_KEY in metadata:
                projected_metadata[OBSERVATIONS_KEY] = metadata[OBSERVATIONS_KEY]
            note = "已验证任务保存的 ComfyUI 提交工作流" if workflow_source == "submitted" else "已验证预备工作流；尚无 ComfyUI 提交确认"
            if workflow_source == "unverified":
                note = f"任务证据未经验证，不能视为实际提交工作流：{proof_error}"
            elif workflow_source is None:
                note = "任务快照尚不完整，未保存预备工作流，也没有提交确认"
            return {
                "success": True,
                "data": {
                    **purpose,
                    "workflow": workflow_obj,
                    "workflowSource": workflow_source,
                    "submitState": submit.get("state"),
                    "sourceProof": {"verified": verified, "code": getattr(proof_error, "code", None),
                                    "message": str(proof_error) if proof_error else None},
                    "prompt": task.prompt_text if task.prompt_text is not None else "未保存提示词",
                    "referenceImages": reference_images if isinstance(reference_images, list) else [],
                    "metadata": projected_metadata,
                    "note": note,
                    "diagnostic": {"workflowJson": task.workflow_json, "metadataJson": task.metadata_json,
                                   "referenceImages": task.reference_images} if proof_error else None,
                },
            }

    # 如果任务保存了工作流JSON，直接返回
    if task.workflow_json:
        try:
            workflow_obj = json.loads(task.workflow_json)
            return {
                "success": True,
                "data": {
                    **purpose,
                    "workflow": workflow_obj,
                    "prompt": task.prompt_text or "未保存提示词"
                }
            }
        except Exception as e:
            return {
                "success": True,
                "data": {
                    **purpose,
                    "workflow": task.workflow_json,
                    "prompt": task.prompt_text or "未保存提示词"
                }
            }

    # 没有保存实际提交的工作流，返回空
    return {
        "success": True,
        "data": {
            **purpose,
            "workflow": None,
            "prompt": task.prompt_text or "未保存提示词",
            "note": "工作流尚未提交到ComfyUI或执行未完成，请稍后查看"
        }
    }


@router.get("/{task_id}/clips/{window_index}/workflow", response_model=dict)
async def get_task_clip_workflow(
    task_id: str,
    window_index: int,
    db: Session = Depends(get_db),
    task_repo: TaskRepository = Depends(get_task_repo),
):
    """获取多 Clip 视频任务中单个 Clip 实际提交的工作流JSON。"""
    import json

    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.type != "shot_video" or not task.shot_id:
        raise HTTPException(status_code=400, detail="该任务不是分镜视频任务")

    purpose = {**TaskService.format_execution_purpose(task), **TaskService.format_video_execution(task)}
    task_only = has_video_execution(task) or purpose["execution_purpose"] != "production"
    expected = TaskService._task_snapshot(task)
    window_plans = []
    if task.video_director_clips:
        try:
            parsed = json.loads(task.video_director_clips)
            window_plans = parsed if isinstance(parsed, list) else []
        except Exception:
            raise HTTPException(status_code=400, detail="任务 Clip 快照格式无效")
    if not window_plans and not task_only:
        shot = db.query(Shot).filter(Shot.id == task.shot_id).first()
        if not shot or not shot.video_director_plan:
            raise HTTPException(status_code=404, detail="未找到分镜视频导演计划")

        try:
            plan = json.loads(shot.video_director_plan)
        except Exception:
            raise HTTPException(status_code=400, detail="分镜视频导演计划格式无效")

        plan_windows = plan.get("window_plans") if isinstance(plan, dict) else None
        window_plans = [window for window in (plan_windows if isinstance(plan_windows, list) else [])
                        if isinstance(window, dict) and window.get("generated_by_task_id") == task.id]
    clip = next((window for window in window_plans if isinstance(window, dict)
                 and str(window.get("window_index") or window.get("clip_index") or "") == str(window_index)), None)
    if not clip and task_only:
        return {"success": True, "data": {**purpose, "workflow": None, "workflowSource": "not_recorded",
                                         "prompt": "未保存提示词", "referenceImages": [],
                                         "note": "该任务未记录此 Clip 的实际提交工作流；不会使用当前分镜计划回填"}}
    if not clip:
        raise HTTPException(status_code=404, detail="Clip 不存在")

    workflow_json = clip.get("workflow_json")
    if not task_only and not workflow_json and clip.get("prompt_id"):
        prompt_state = await TaskService(db).comfyui_service.client.get_prompt_state(str(clip.get("prompt_id")))
        prompt_history = prompt_state.get("history") if prompt_state.get("state") in {"history", "completed"} else None
        prompt_payload = prompt_history.get("prompt") if isinstance(prompt_history, dict) else None
        if (isinstance(prompt_payload, list) and len(prompt_payload) > 2
                and prompt_payload[1] == clip["prompt_id"] and isinstance(prompt_payload[2], dict)):
            workflow_json = prompt_payload[2]
            clip["workflow_json"] = workflow_json
            from app.models.task import Task
            with db.no_autoflush:
                count = db.query(Task).filter(*[
                    getattr(Task, key) == value for key, value in expected.items()
                ]).update({"video_director_clips": json.dumps(window_plans, ensure_ascii=False)}, synchronize_session=False)
                if count == 1:
                    db.commit()
                    db.refresh(task)
                else:
                    db.rollback()
                    return {"success": True, "data": {**purpose, "workflow": None, "workflowSource": "not_recorded",
                                                     "note": "任务证据已更改，未回填旧工作流，请重新读取"}}

    return {
        "success": True,
        "data": {
            **purpose,
            "workflow": workflow_json,
            "workflowSource": "recorded" if workflow_json else "not_recorded",
            "prompt": clip.get("prompt_text") or "未保存提示词",
            "referenceImages": clip.get("reference_images") if isinstance(clip.get("reference_images"), list) else [],
            "note": None if clip.get("workflow_json") else "该 Clip 尚未保存实际提交的工作流 JSON",
        }
    }
