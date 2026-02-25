"""
任务 API 路由

只负责请求/响应处理，业务逻辑委托给 TaskService
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.models.novel import Novel, Chapter
from app.models.workflow import Workflow
from app.repositories import TaskRepository
from app.services.task_service import TaskService

router = APIRouter()


def get_task_repo(db: Session = Depends(get_db)) -> TaskRepository:
    """获取 TaskRepository 实例"""
    return TaskRepository(db)


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    """获取 TaskService 实例"""
    return TaskService(db)


# ==================== 任务列表 ====================

@router.get("/", response_model=dict)
async def list_tasks(
        status: Optional[str] = None,
        type: Optional[str] = None,
        limit: int = 50,
        db: Session = Depends(get_db),
        task_repo: TaskRepository = Depends(get_task_repo)
):
    """获取任务列表"""
    tasks = task_repo.list_by_filters(status=status, task_type=type, limit=limit)

    # 获取所有需要的小说、章节和工作流信息
    novel_ids = {t.novel_id for t in tasks if t.novel_id}
    chapter_ids = {t.chapter_id for t in tasks if t.chapter_id}
    workflow_ids = {t.workflow_id for t in tasks if t.workflow_id}

    novels = {n.id: n for n in db.query(Novel).filter(Novel.id.in_(novel_ids)).all()} if novel_ids else {}
    chapters = {c.id: c for c in db.query(Chapter).filter(Chapter.id.in_(chapter_ids)).all()} if chapter_ids else {}
    workflows = {w.id: w for w in
                 db.query(Workflow).filter(Workflow.id.in_(workflow_ids)).all()} if workflow_ids else {}

    return {
        "success": True,
        "data": TaskService.format_task_list(tasks, novels, chapters, workflows)
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


# ==================== 角色任务 ====================

@router.post("/character/{character_id}/generate-portrait")
async def generate_character_portrait(
        character_id: str,
        task_service: TaskService = Depends(get_task_service)
):
    """生成角色人设图任务"""
    return task_service.create_character_portrait_task(character_id)


# ==================== 场景任务 ====================

@router.post("/scene/{scene_id}/generate-image")
async def generate_scene_image(
        scene_id: str,
        task_service: TaskService = Depends(get_task_service)
):
    """生成场景图任务"""
    return task_service.create_scene_image_task(scene_id)


# ==================== 任务操作 ====================

@router.delete("/{task_id}")
async def delete_task(task_id: str, task_repo: TaskRepository = Depends(get_task_repo)):
    """删除任务"""
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

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
