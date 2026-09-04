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
from app.services.video_director_plan_service import VideoDirectorPlanService
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
    task_repo: TaskRepository = Depends(get_task_repo)
):
    """获取任务提交给ComfyUI的工作流JSON"""
    import json
    
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 如果任务保存了工作流JSON，直接返回
    if task.workflow_json:
        try:
            workflow_obj = json.loads(task.workflow_json)
            return {
                "success": True,
                "data": {
                    "workflow": workflow_obj,
                    "prompt": task.prompt_text or "未保存提示词"
                }
            }
        except Exception as e:
            return {
                "success": True,
                "data": {
                    "workflow": task.workflow_json,
                    "prompt": task.prompt_text or "未保存提示词"
                }
            }

    # 没有保存实际提交的工作流，返回空
    return {
        "success": True,
        "data": {
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

    workflow_json = clip.get("workflow_json")
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
                def mutate(plan: dict) -> dict:
                    plan_windows = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
                    for plan_window in plan_windows:
                        if isinstance(plan_window, dict) and int(plan_window.get("window_index") or 0) == window_index:
                            plan_window["workflow_json"] = workflow_json
                            break
                    plan["window_plans"] = plan_windows
                    return plan

                VideoDirectorPlanService(db).mutate(shot.id, mutate)
            db.commit()

    return {
        "success": True,
        "data": {
            "workflow": workflow_json,
            "prompt": clip.get("prompt_text") or "未保存提示词",
            "referenceImages": clip.get("reference_images") if isinstance(clip.get("reference_images"), list) else [],
            "note": None if clip.get("workflow_json") else "该 Clip 尚未保存实际提交的工作流 JSON",
        }
    }
