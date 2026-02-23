from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import json
import uuid

from app.core.database import get_db
from app.core.config import get_settings
from app.models.novel import Character, Novel
from app.models.prompt_template import PromptTemplate
from app.services.comfyui import ComfyUIService
from app.services.llm_service import LLMService

router = APIRouter()
settings = get_settings()
comfyui_service = ComfyUIService()


def get_llm_service() -> LLMService:
    """获取 LLMService 实例（每次调用创建新实例以获取最新配置）"""
    return LLMService()

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
            "startChapter": c.start_chapter,
            "endChapter": c.end_chapter,
            "isIncremental": c.is_incremental,
            "sourceRange": c.source_range,
            "lastParsedAt": c.last_parsed_at.isoformat() if c.last_parsed_at else None,
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
            "startChapter": character.start_chapter,
            "endChapter": character.end_chapter,
            "isIncremental": character.is_incremental,
            "sourceRange": character.source_range,
            "lastParsedAt": character.last_parsed_at.isoformat() if character.last_parsed_at else None,
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


@router.delete("/")
async def delete_characters_by_novel(novel_id: str = Query(..., description="小说ID"), db: Session = Depends(get_db)):
    """删除指定小说的所有角色"""
    # 检查小说是否存在
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 删除该小说的所有角色
    result = db.query(Character).filter(Character.novel_id == novel_id).delete()
    db.commit()
    
    # 删除角色图片目录
    from app.services.file_storage import file_storage
    file_storage.delete_characters_dir(novel_id)
    
    return {"success": True, "message": f"已删除 {result} 个角色", "deleted_count": result}


@router.post("/clear-characters-dir")
async def clear_characters_dir(novel_id: str = Query(..., description="小说ID"), db: Session = Depends(get_db)):
    """清空小说的角色图片目录（用于批量重新生成前）"""
    # 检查小说是否存在
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 清空角色图片目录
    from app.services.file_storage import file_storage
    success = file_storage.delete_characters_dir(novel_id)
    
    if success:
        return {"success": True, "message": "角色图片目录已清空"}
    else:
        raise HTTPException(status_code=500, detail="清空角色图片目录失败")


@router.post("/{character_id}/generate-portrait")
async def generate_portrait(
    character_id: str,
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
    
    # 后台任务生成图片 - 使用 asyncio.create_task 实现真正并发
    import asyncio
    asyncio.create_task(
        generate_character_portrait_task(
            task_id,
            character_id,
            character.name,
            character.appearance,
            character.description
        )
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


@router.get("/{character_id}/prompt", response_model=dict)
async def get_character_prompt(character_id: str, db: Session = Depends(get_db)):
    """获取角色生成时使用的拼接后提示词"""
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 获取角色所属小说
    novel = db.query(Novel).filter(Novel.id == character.novel_id).first()
    
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
    prompt = build_character_prompt(
        name=character.name,
        appearance=character.appearance,
        description=character.description,
        template=template.template if template else None
    )
    
    return {
        "success": True,
        "data": {
            "prompt": prompt,
            "templateName": template.name if template else "默认模板",
            "templateId": template.id if template else None,
            "isSystem": template.is_system if template else False,
            "template": template.template if template else None,
            "appearance": character.appearance,
            "description": character.description
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
        
        # 获取角色信息以获取 novel_id 和 style
        from app.core.database import SessionLocal
        from app.models.novel import Novel, Character
        from app.models.prompt_template import PromptTemplate
        import json
        
        db = SessionLocal()
        style = "anime style, high quality, detailed"
        novel_id = None
        try:
            character = db.query(Character).filter(Character.id == character_id).first()
            if character and character.novel_id:
                novel_id = character.novel_id
                novel = db.query(Novel).filter(Novel.id == novel_id).first()
                if novel and novel.prompt_template_id:
                    template = db.query(PromptTemplate).filter(
                        PromptTemplate.id == novel.prompt_template_id
                    ).first()
                    if template:
                        # 从模板提取 style
                        if hasattr(template, 'style') and template.style:
                            style = template.style
                        else:
                            # 从模板内容提取
                            try:
                                template_data = json.loads(template.template)
                                if isinstance(template_data, dict) and "style" in template_data:
                                    style = template_data["style"]
                            except:
                                style = template.template.replace("{appearance}", "").replace("{description}", "").strip(", ")
        finally:
            db.close()
        
        # 调用 ComfyUI 生成图片，传递 style
        result = await comfyui_service.generate_character_image(
            prompt,
            novel_id=novel_id,
            character_name=name,
            style=style
        )
        
        # 保存实际提交给ComfyUI的工作流
        if result.get("submitted_workflow"):
            generation_tasks[task_id]["submitted_workflow"] = json.dumps(
                result["submitted_workflow"], ensure_ascii=False, indent=2
            )
            print(f"[CharacterTask {task_id}] Saved submitted workflow")
        
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
        appearance = await get_llm_service().generate_character_appearance(
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


def build_character_prompt(name: str, appearance: str, description: str, template: str = None) -> str:
    """构建角色人设图提示词
    
    Args:
        name: 角色名称
        appearance: 外貌描述
        description: 角色描述（已废弃，不再使用）
        template: 提示词模板，包含 {appearance} 和 {description} 占位符
    """
    # 根据角色名称检测动物类型，添加英文强调词
    animal_keyword = detect_animal_type(name, appearance)
    
    if template:
        # 使用模板构建提示词，只使用 appearance，不使用 description
        prompt = template.replace("{appearance}", appearance or "").replace("{description}", "")
        # 在开头添加动物类型强调
        if animal_keyword:
            prompt = f"{animal_keyword} character, " + prompt
        # 清理多余的逗号和空格
        prompt = " ".join(prompt.split())
        prompt = prompt.replace(" ,", ",").replace(",,", ",").strip(", ")
        return prompt
    
    # 默认提示词
    base_prompt = "character portrait, high quality, detailed, "
    
    if animal_keyword:
        base_prompt = f"{animal_keyword} character, " + base_prompt
    
    if appearance:
        base_prompt += appearance + ", "
    
    if description:
        base_prompt += description + ", "
    
    base_prompt += "single character, centered, clean background, professional artwork"
    
    return base_prompt


def detect_animal_type(name: str, appearance: str) -> str:
    """检测角色动物类型，返回英文关键词"""
    name_lower = (name or "").lower()
    appearance_lower = (appearance or "").lower()
    
    # 动物关键词映射
    animal_map = {
        "horse": ["马", "horse", "pony", "stallion", "mare"],
        "cow": ["牛", "cow", "bull", "ox", "cattle", "buffalo", "bison"],
        "squirrel": ["松鼠", "squirrel", "chipmunk"],
        "fox": ["狐狸", "fox"],
        "dog": ["狗", "dog", "puppy", "canine"],
        "cat": ["猫", "cat", "kitten", "feline"],
        "rabbit": ["兔", "rabbit", "bunny", "hare"],
        "bear": ["熊", "bear"],
        "wolf": ["狼", "wolf"],
        "tiger": ["虎", "tiger"],
        "lion": ["狮", "lion"],
        "elephant": ["象", "elephant"],
        "pig": ["猪", "pig", "boar", "hog"],
        "sheep": ["羊", "sheep", "lamb", "goat"],
        "chicken": ["鸡", "chicken", "hen", "rooster"],
        "duck": ["鸭", "duck"],
        "mouse": ["鼠", "mouse", "rat"],
        "deer": ["鹿", "deer"],
        "monkey": ["猴", "monkey", "ape"],
    }
    
    combined_text = name_lower + " " + appearance_lower
    
    for animal_type, keywords in animal_map.items():
        for keyword in keywords:
            if keyword in combined_text:
                return animal_type
    
    return None
