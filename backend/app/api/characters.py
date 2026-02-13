from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
import json
import uuid

from app.core.database import get_db
from app.core.config import get_settings
from app.models.novel import Character, Novel
from app.services.comfyui import ComfyUIService
from app.services.deepseek import DeepSeekService

router = APIRouter()
settings = get_settings()
comfyui_service = ComfyUIService()
deepseek_service = DeepSeekService()

# 存储生成任务状态（生产环境应使用 Redis）
generation_tasks = {}


@router.get("/", response_model=dict)
async def list_characters(novel_id: str = None, db: Session = Depends(get_db)):
    """获取角色列表"""
    query = db.query(Character)
    if novel_id:
        query = query.filter(Character.novel_id == novel_id)
    characters = query.order_by(Character.created_at.desc()).all()
    
    result = []
    for c in characters:
        novel = db.query(Novel).filter(Novel.id == c.novel_id).first()
        result.append({
            "id": c.id,
            "novelId": c.novel_id,
            "name": c.name,
            "description": c.description,
            "appearance": c.appearance,
            "imageUrl": c.image_url,
            "generatingStatus": c.generating_status,
            "portraitTaskId": c.portrait_task_id,
            "novelName": novel.title if novel else None,
            "createdAt": c.created_at.isoformat() if c.created_at else None,
            "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
        })
    
    return {"success": True, "data": result}


@router.get("/{character_id}", response_model=dict)
async def get_character(character_id: str, db: Session = Depends(get_db)):
    """获取角色详情"""
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    novel = db.query(Novel).filter(Novel.id == character.novel_id).first()
    
    return {
        "success": True,
        "data": {
            "id": character.id,
            "novelId": character.novel_id,
            "name": character.name,
            "description": character.description,
            "appearance": character.appearance,
            "imageUrl": character.image_url,
            "generatingStatus": character.generating_status,
            "portraitTaskId": character.portrait_task_id,
            "novelName": novel.title if novel else None,
            "createdAt": character.created_at.isoformat() if character.created_at else None,
            "updatedAt": character.updated_at.isoformat() if character.updated_at else None,
        }
    }


@router.post("/", response_model=dict)
async def create_character(
    data: dict,
    db: Session = Depends(get_db)
):
    """创建角色"""
    # 验证小说存在
    novel = db.query(Novel).filter(Novel.id == data.get('novelId')).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    character = Character(
        novel_id=data.get('novelId'),
        name=data.get('name'),
        description=data.get('description', ''),
        appearance=data.get('appearance', ''),
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    
    return {
        "success": True,
        "data": {
            "id": character.id,
            "novelId": character.novel_id,
            "name": character.name,
            "description": character.description,
            "appearance": character.appearance,
            "imageUrl": character.image_url,
            "novelName": novel.title,
            "createdAt": character.created_at.isoformat() if character.created_at else None,
        }
    }


@router.put("/{character_id}", response_model=dict)
async def update_character(
    character_id: str,
    data: dict,
    db: Session = Depends(get_db)
):
    """更新角色"""
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    character.name = data.get('name', character.name)
    character.description = data.get('description', character.description)
    character.appearance = data.get('appearance', character.appearance)
    
    db.commit()
    db.refresh(character)
    
    novel = db.query(Novel).filter(Novel.id == character.novel_id).first()
    
    return {
        "success": True,
        "data": {
            "id": character.id,
            "novelId": character.novel_id,
            "name": character.name,
            "description": character.description,
            "appearance": character.appearance,
            "imageUrl": character.image_url,
            "novelName": novel.title if novel else None,
            "updatedAt": character.updated_at.isoformat() if character.updated_at else None,
        }
    }


@router.delete("/{character_id}")
async def delete_character(character_id: str, db: Session = Depends(get_db)):
    """删除角色"""
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    db.delete(character)
    db.commit()
    
    return {"success": True, "message": "删除成功"}


@router.post("/{character_id}/generate-portrait")
async def generate_portrait(
    character_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """生成角色人设图"""
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 生成任务ID
    task_id = str(uuid.uuid4())
    generation_tasks[task_id] = {
        "character_id": character_id,
        "status": "pending",
        "image_url": None,
        "message": None
    }
    
    # 后台任务生成图片
    background_tasks.add_task(
        generate_character_portrait_task,
        task_id,
        character_id,
        character.name,
        character.appearance,
        character.description
    )
    
    return {
        "success": True,
        "data": {
            "taskId": task_id,
            "status": "pending",
            "message": "人设图生成任务已创建"
        }
    }


@router.get("/{character_id}/portrait-status")
async def get_portrait_status(character_id: str, task_id: str = None, db: Session = Depends(get_db)):
    """获取人设图生成状态"""
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 如果已有图片，直接返回完成状态
    if character.image_url:
        return {
            "success": True,
            "data": {
                "status": "completed",
                "imageUrl": character.image_url,
                "message": "人设图已生成"
            }
        }
    
    # 查找进行中的任务
    if task_id and task_id in generation_tasks:
        task = generation_tasks[task_id]
        if task["character_id"] == character_id:
            return {
                "success": True,
                "data": {
                    "status": task["status"],
                    "imageUrl": task["image_url"],
                    "message": task["message"]
                }
            }
    
    return {
        "success": True,
        "data": {
            "status": "pending",
            "imageUrl": None,
            "message": "等待生成"
        }
    }


async def generate_character_portrait_task(
    task_id: str,
    character_id: str,
    name: str,
    appearance: str,
    description: str
):
    """后台任务：生成角色人设图"""
    try:
        generation_tasks[task_id]["status"] = "running"
        generation_tasks[task_id]["message"] = "正在调用 ComfyUI 生成图片..."
        
        # 构建提示词
        prompt = build_character_prompt(name, appearance, description)
        
        # 调用 ComfyUI 生成图片
        result = await comfyui_service.generate_character_image(prompt)
        
        if result.get("success"):
            generation_tasks[task_id]["status"] = "completed"
            generation_tasks[task_id]["image_url"] = result.get("image_url")
            generation_tasks[task_id]["message"] = "生成成功"
            
            # 更新数据库
            from app.core.database import SessionLocal
            db = SessionLocal()
            try:
                character = db.query(Character).filter(Character.id == character_id).first()
                if character:
                    character.image_url = result.get("image_url")
                    db.commit()
            finally:
                db.close()
        else:
            generation_tasks[task_id]["status"] = "failed"
            generation_tasks[task_id]["message"] = result.get("message", "生成失败")
            
    except Exception as e:
        generation_tasks[task_id]["status"] = "failed"
        generation_tasks[task_id]["message"] = str(e)


@router.post("/{character_id}/generate-appearance", response_model=dict)
async def generate_appearance(
    character_id: str,
    db: Session = Depends(get_db)
):
    """使用 DeepSeek AI 智能生成角色外貌描述"""
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    try:
        # 调用 DeepSeek 生成外貌描述
        appearance = await deepseek_service.generate_character_appearance(
            character_name=character.name,
            description=character.description,
            style="anime"
        )
        
        # 更新角色
        character.appearance = appearance
        db.commit()
        
        return {
            "success": True,
            "data": {
                "appearance": appearance,
                "message": "外貌描述生成成功"
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"生成失败: {str(e)}"
        }


def build_character_prompt(name: str, appearance: str, description: str) -> str:
    """构建角色人设图提示词"""
    base_prompt = "character portrait, high quality, detailed, "
    
    if appearance:
        base_prompt += appearance + ", "
    
    if description:
        # 提取描述中的关键外貌特征
        base_prompt += description + ", "
    
    base_prompt += "single character, centered, clean background, professional artwork"
    
    return base_prompt
