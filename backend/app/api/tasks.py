from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app.core.database import get_db
from app.models.task import Task
from app.models.novel import Character, Chapter
from app.services.comfyui import ComfyUIService

router = APIRouter()
comfyui_service = ComfyUIService()


@router.get("/", response_model=dict)
async def list_tasks(
    status: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """获取任务列表"""
    query = db.query(Task).order_by(Task.created_at.desc())
    
    if status:
        query = query.filter(Task.status == status)
    if type:
        query = query.filter(Task.type == type)
    
    tasks = query.limit(limit).all()
    
    return {
        "success": True,
        "data": [
            {
                "id": t.id,
                "type": t.type,
                "name": t.name,
                "description": t.description,
                "status": t.status,
                "progress": t.progress,
                "currentStep": t.current_step,
                "resultUrl": t.result_url,
                "errorMessage": t.error_message,
                "workflowId": t.workflow_id,
                "workflowName": t.workflow_name,
                "novelId": t.novel_id,
                "chapterId": t.chapter_id,
                "characterId": t.character_id,
                "createdAt": t.created_at.isoformat() if t.created_at else None,
                "startedAt": t.started_at.isoformat() if t.started_at else None,
                "completedAt": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in tasks
        ]
    }


@router.get("/{task_id}", response_model=dict)
async def get_task(task_id: str, db: Session = Depends(get_db)):
    """获取任务详情"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return {
        "success": True,
        "data": {
            "id": task.id,
            "type": task.type,
            "name": task.name,
            "description": task.description,
            "status": task.status,
            "progress": task.progress,
            "currentStep": task.current_step,
            "resultUrl": task.result_url,
            "errorMessage": task.error_message,
            "workflowId": task.workflow_id,
            "workflowName": task.workflow_name,
            "novelId": task.novel_id,
            "chapterId": task.chapter_id,
            "characterId": task.character_id,
            "comfyuiPromptId": task.comfyui_prompt_id,
            "createdAt": task.created_at.isoformat() if task.created_at else None,
            "startedAt": task.started_at.isoformat() if task.started_at else None,
            "completedAt": task.completed_at.isoformat() if task.completed_at else None,
        }
    }


@router.post("/character/{character_id}/generate-portrait")
async def generate_character_portrait(
    character_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """生成角色人设图任务"""
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 检查是否已有进行中的任务
    existing_task = db.query(Task).filter(
        Task.character_id == character_id,
        Task.type == "character_portrait",
        Task.status.in_(["pending", "running"])
    ).first()
    
    if existing_task:
        return {
            "success": True,
            "message": "已有进行中的生成任务",
            "data": {
                "taskId": existing_task.id,
                "status": existing_task.status
            }
        }
    
    # 创建任务
    task = Task(
        type="character_portrait",
        name=f"生成角色形象: {character.name}",
        description=f"为角色 '{character.name}' 生成人设图",
        novel_id=character.novel_id,
        character_id=character_id,
        status="pending"
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    
    # 后台执行生成
    background_tasks.add_task(
        generate_portrait_task,
        task.id,
        character_id,
        character.name,
        character.appearance,
        character.description
    )
    
    return {
        "success": True,
        "message": "人设图生成任务已创建",
        "data": {
            "taskId": task.id,
            "status": "pending"
        }
    }


@router.delete("/{task_id}")
async def delete_task(task_id: str, db: Session = Depends(get_db)):
    """删除任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    db.delete(task)
    db.commit()
    
    return {"success": True, "message": "任务已删除"}


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """重试失败的任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    if task.status not in ["failed", "completed"]:
        raise HTTPException(status_code=400, detail="只能重试失败或已完成的任务")
    
    # 重置任务状态
    task.status = "pending"
    task.progress = 0
    task.current_step = None
    task.error_message = None
    task.result_url = None
    task.completed_at = None
    db.commit()
    
    # 根据任务类型重新执行
    if task.type == "character_portrait" and task.character_id:
        character = db.query(Character).filter(Character.id == task.character_id).first()
        if character:
            background_tasks.add_task(
                generate_portrait_task,
                task.id,
                character.id,
                character.name,
                character.appearance,
                character.description
            )
    
    return {
        "success": True,
        "message": "任务已重新启动",
        "data": {
            "taskId": task.id,
            "status": "pending"
        }
    }


async def generate_portrait_task(
    task_id: str,
    character_id: str,
    name: str,
    appearance: str,
    description: str
):
    """后台任务：生成角色人设图"""
    from app.core.database import SessionLocal
    from app.models.workflow import Workflow
    
    db = SessionLocal()
    try:
        # 获取任务
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        
        # 获取当前激活的 character 工作流
        workflow = db.query(Workflow).filter(
            Workflow.type == "character",
            Workflow.is_active == True
        ).first()
        
        # 记录工作流信息
        if workflow:
            task.workflow_id = workflow.id
            task.workflow_name = workflow.name
            task.current_step = f"使用工作流: {workflow.name}"
        else:
            task.current_step = "使用默认工作流"
        
        # 更新任务状态为运行中
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()
        
        # 构建提示词
        prompt = build_character_prompt(name, appearance, description)
        task.current_step = f"提示词: {prompt[:100]}..."
        db.commit()
        
        # 调用 ComfyUI 生成图片（使用指定的工作流）
        workflow_json = workflow.workflow_json if workflow else None
        result = await comfyui_service.generate_character_image(prompt, workflow_json=workflow_json)
        
        if result.get("success"):
            task.status = "completed"
            task.progress = 100
            task.result_url = result.get("image_url")
            task.current_step = "生成完成"
            task.completed_at = datetime.utcnow()
            
            # 更新角色图片
            character = db.query(Character).filter(Character.id == character_id).first()
            if character:
                character.image_url = result.get("image_url")
        else:
            task.status = "failed"
            task.error_message = result.get("message", "生成失败")
            task.current_step = "生成失败"
        
        db.commit()
        
    except Exception as e:
        task.status = "failed"
        task.error_message = str(e)
        task.current_step = "任务异常"
        db.commit()
    finally:
        db.close()


def build_character_prompt(name: str, appearance: str, description: str) -> str:
    """构建角色人设图提示词"""
    base_prompt = "character portrait, high quality, detailed, "
    
    if appearance:
        base_prompt += appearance + ", "
    
    if description:
        # 提取描述中的关键外貌特征
        base_prompt += description + ", "
    
    base_prompt += "single character, centered, clean background, professional artwork, 8k"
    
    return base_prompt
