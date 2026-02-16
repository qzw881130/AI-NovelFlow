from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app.core.database import get_db
from app.models.task import Task
from app.models.novel import Character, Chapter, Novel
from app.models.prompt_template import PromptTemplate
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
    from app.models.novel import Novel, Chapter
    
    query = db.query(Task).order_by(Task.created_at.desc())
    
    if status:
        query = query.filter(Task.status == status)
    if type:
        query = query.filter(Task.type == type)
    
    tasks = query.limit(limit).all()
    
    # 获取所有需要的小说和章节信息
    novel_ids = {t.novel_id for t in tasks if t.novel_id}
    chapter_ids = {t.chapter_id for t in tasks if t.chapter_id}
    
    novels = {n.id: n for n in db.query(Novel).filter(Novel.id.in_(novel_ids)).all()} if novel_ids else {}
    chapters = {c.id: c for c in db.query(Chapter).filter(Chapter.id.in_(chapter_ids)).all()} if chapter_ids else {}
    
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
                "hasWorkflowJson": t.workflow_json is not None,
                "hasPromptText": t.prompt_text is not None,
                "novelId": t.novel_id,
                "novelName": novels.get(t.novel_id).title if t.novel_id and t.novel_id in novels else None,
                "chapterId": t.chapter_id,
                "chapterTitle": chapters.get(t.chapter_id).title if t.chapter_id and t.chapter_id in chapters else None,
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
            "workflowJson": task.workflow_json,
            "promptText": task.prompt_text,
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
    
    # 检查是否已有进行中的生成任务
    if character.generating_status == "running":
        return {
            "success": False,
            "message": "该角色正在生成形象中，请稍后再试"
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
    
    # 更新角色生成状态
    character.generating_status = "running"
    character.portrait_task_id = task.id
    db.commit()
    
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


@router.post("/cancel-all/", response_model=dict)
async def cancel_all_tasks(db: Session = Depends(get_db)):
    """
    终止所有正在进行或待处理的任务
    
    执行顺序：
    1. 先清空 ComfyUI 队列（清除所有等待中的任务）
    2. 再中断当前正在执行的任务
    """
    # 获取所有 pending 或 running 的任务
    active_tasks = db.query(Task).filter(
        Task.status.in_(["pending", "running"])
    ).all()
    
    if not active_tasks:
        return {
            "success": True,
            "message": "没有需要终止的任务",
            "cancelled_count": 0
        }
    
    # 检查是否有 running 状态的任务
    has_running_task = any(t.status == "running" for t in active_tasks)
    
    print(f"[CancelAll] Found {len(active_tasks)} active tasks, has_running: {has_running_task}")
    
    cancel_result = {
        "queue_cleared": False,
        "interrupted": False
    }
    
    # 1. 【第一步】清空 ComfyUI 队列（先清除等待中的任务）
    try:
        print(f"[CancelAll] Step 1: Clearing ComfyUI queue")
        clear_result = await comfyui_service.clear_queue()
        cancel_result["queue_cleared"] = clear_result.get("success", False)
        print(f"[CancelAll] Clear queue result: {clear_result}")
    except Exception as e:
        print(f"[CancelAll] Clear queue error: {e}")
    
    # 2. 【第二步】中断当前正在执行的任务
    if has_running_task:
        try:
            print(f"[CancelAll] Step 2: Interrupting running task")
            interrupt_result = await comfyui_service.interrupt_execution()
            cancel_result["interrupted"] = interrupt_result.get("success", False)
            print(f"[CancelAll] Interrupt result: {interrupt_result}")
        except Exception as e:
            print(f"[CancelAll] Interrupt error: {e}")
    
    # 更新所有任务状态为 failed
    cancelled_count = 0
    failed_count = 0
    for task in active_tasks:
        try:
            task.status = "failed"
            task.error_message = "任务被用户终止"
            task.current_step = "已终止"
            cancelled_count += 1
        except Exception as e:
            print(f"[CancelAll] Failed to update task {task.id}: {e}")
            failed_count += 1
    
    db.commit()
    
    # 构建返回消息
    message_parts = []
    if cancelled_count > 0:
        message_parts.append(f"已终止 {cancelled_count} 个任务")
    if cancel_result.get("queue_cleared"):
        message_parts.append("已清空队列")
    if cancel_result.get("interrupted"):
        message_parts.append("已中断运行中任务")
    if failed_count > 0:
        message_parts.append(f"{failed_count} 个更新失败")
    
    return {
        "success": True,
        "message": "；".join(message_parts) if message_parts else "操作完成",
        "cancelled_count": cancelled_count,
        "failed_count": failed_count,
        "details": cancel_result
    }


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


@router.get("/{task_id}/workflow", response_model=dict)
async def get_task_workflow(task_id: str, db: Session = Depends(get_db)):
    """获取任务提交给ComfyUI的工作流JSON"""
    from app.models.workflow import Workflow
    
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 如果任务保存了工作流JSON，直接返回
    if task.workflow_json:
        try:
            import json
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
    # （避免显示模板造成误导）
    return {
        "success": True,
        "data": {
            "workflow": None,
            "prompt": task.prompt_text or "未保存提示词",
            "note": "工作流尚未提交到ComfyUI或执行未完成，请稍后查看"
        }
    }
    
    return {
        "success": False,
        "message": "无法获取工作流信息"
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
    from app.services.file_storage import file_storage
    
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
        
        # 获取角色所属小说
        character = db.query(Character).filter(Character.id == character_id).first()
        novel = db.query(Novel).filter(Novel.id == character.novel_id).first() if character else None
        
        # 获取提示词模板
        template = None
        if novel and novel.prompt_template_id:
            template = db.query(PromptTemplate).filter(
                PromptTemplate.id == novel.prompt_template_id
            ).first()
        
        # 如果没有指定模板，使用默认系统模板
        if not template:
            template = db.query(PromptTemplate).filter(
                PromptTemplate.is_system == True
            ).order_by(PromptTemplate.created_at.asc()).first()
        
        # 构建提示词
        prompt = build_character_prompt(name, appearance, description, template.template if template else None)
        task.current_step = f"使用模板: {template.name if template else '默认'}, 提示词: {prompt[:80]}..."
        
        # 保存提示词
        task.prompt_text = prompt
        db.commit()
        
        # 获取工作流JSON字符串（不保存到task，等ComfyUI返回实际提交版本）
        workflow_json_str = workflow.workflow_json if workflow else None
        print(f"[Task] Workflow JSON available: {workflow_json_str is not None}, length: {len(workflow_json_str) if workflow_json_str else 0}")
        
        # 调用 ComfyUI 生成图片（使用指定的工作流）
        print(f"[Task] Generating image with workflow: {workflow.name if workflow else 'default'}")
        print(f"[Task] Workflow JSON length: {len(workflow_json_str) if workflow_json_str else 0}")
        print(f"[Task] Novel ID: {task.novel_id}, Character: {name}")
        
        # 获取工作流的节点映射配置
        node_mapping = None
        if workflow and workflow.node_mapping:
            try:
                import json
                node_mapping = json.loads(workflow.node_mapping)
                print(f"[Task] Using node mapping: {node_mapping}")
            except Exception as e:
                print(f"[Task] Failed to parse node_mapping: {e}")
        
        result = await comfyui_service.generate_character_image(
            prompt, 
            workflow_json=workflow_json_str,
            novel_id=task.novel_id,
            character_name=name,
            aspect_ratio=novel.aspect_ratio if novel else None,
            node_mapping=node_mapping
        )
        
        print(f"[Task] Generation result: {result}")
        
        # 保存实际提交给ComfyUI的工作流（替换参数后的）
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
            print(f"[Task] Saved submitted workflow to task")
        
        if result.get("success"):
            image_url = result.get("image_url")
            
            # 下载图片到本地存储
            task.current_step = "下载图片到服务器..."
            db.commit()
            
            try:
                local_path = await file_storage.download_image(
                    url=image_url,
                    novel_id=task.novel_id or "default",
                    character_name=name,
                    image_type="character"
                )
                
                if local_path:
                    # 构建本地可访问的URL (通过静态文件服务)
                    relative_path = local_path.replace(str(file_storage.base_dir), "")
                    local_url = f"/api/files/{relative_path.lstrip('/')}"
                    task.result_url = local_url
                    task.current_step = "生成完成，图片已保存"
                else:
                    # 下载失败，使用原始URL
                    task.result_url = image_url
                    task.current_step = "生成完成，使用远程图片"
            except Exception as e:
                print(f"[Task] Failed to download image: {e}")
                task.result_url = image_url
                task.current_step = "生成完成，使用远程图片"
            
            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.utcnow()
            
            # 更新角色图片和状态
            character = db.query(Character).filter(Character.id == character_id).first()
            if character:
                character.image_url = task.result_url
                character.generating_status = "completed"
        else:
            task.status = "failed"
            task.error_message = result.get("message", "生成失败")
            task.current_step = "生成失败"
            
            # 更新角色状态为失败
            character = db.query(Character).filter(Character.id == character_id).first()
            if character:
                character.generating_status = "failed"
        
        db.commit()
        
    except Exception as e:
        task.status = "failed"
        task.error_message = str(e)
        task.current_step = "任务异常"
        
        # 更新角色状态为失败
        try:
            character = db.query(Character).filter(Character.id == character_id).first()
            if character:
                character.generating_status = "failed"
        except:
            pass
        
        db.commit()
    finally:
        db.close()


def build_character_prompt(name: str, appearance: str, description: str, template: str = None) -> str:
    """构建角色人设图提示词
    
    Args:
        name: 角色名称
        appearance: 外貌描述
        description: 角色描述
        template: 提示词模板，包含 {appearance} 和 {description} 占位符
    """
    if template:
        # 使用模板构建提示词
        prompt = template.replace("{appearance}", appearance or "").replace("{description}", description or "")
        # 清理多余的逗号和空格
        prompt = " ".join(prompt.split())
        prompt = prompt.replace(" ,", ",").replace(",,", ",").strip(", ")
        return prompt
    
    # 默认提示词
    base_prompt = "character portrait, high quality, detailed, "
    
    if appearance:
        base_prompt += appearance + ", "
    
    if description:
        base_prompt += description + ", "
    
    base_prompt += "single character, centered, clean background, professional artwork, 8k"
    
    return base_prompt
