from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.novel import Character, Novel
from app.models.prompt_template import PromptTemplate
from app.services.comfyui import ComfyUIService
from app.services.llm_service import LLMService
from app.services.prompt_builder import (
    build_character_prompt
)
from app.repositories import NovelRepository, CharacterRepository

router = APIRouter()
settings = get_settings()
comfyui_service = ComfyUIService()


def get_llm_service() -> LLMService:
    """获取 LLMService 实例（每次调用创建新实例以获取最新配置）"""
    return LLMService()


def get_novel_repo(db: Session = Depends(get_db)) -> NovelRepository:
    """获取 NovelRepository 实例"""
    return NovelRepository(db)


def get_character_repo(db: Session = Depends(get_db)) -> CharacterRepository:
    """获取 CharacterRepository 实例"""
    return CharacterRepository(db)


@router.get("/", response_model=dict)
async def list_characters(novel_id: str = None, db: Session = Depends(get_db), novel_repo: NovelRepository = Depends(get_novel_repo), character_repo: CharacterRepository = Depends(get_character_repo)):
    """获取角色列表"""
    if novel_id:
        characters = character_repo.list_by_novel(novel_id)
    else:
        characters = db.query(Character).order_by(Character.created_at.desc()).all()
    
    result = []
    for c in characters:
        novel = novel_repo.get_by_id(c.novel_id)
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
async def get_character(character_id: str, novel_repo: NovelRepository = Depends(get_novel_repo), character_repo: CharacterRepository = Depends(get_character_repo)):
    """获取角色详情"""
    character = character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    novel = novel_repo.get_by_id(character.novel_id)
    
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
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """创建角色"""
    # 验证小说存在
    novel = novel_repo.get_by_id(data.get('novelId'))
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
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    character_repo: CharacterRepository = Depends(get_character_repo)
):
    """更新角色"""
    character = character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    character.name = data.get('name', character.name)
    character.description = data.get('description', character.description)
    character.appearance = data.get('appearance', character.appearance)
    
    db.commit()
    db.refresh(character)
    
    novel = novel_repo.get_by_id(character.novel_id)
    
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
async def delete_character(character_id: str, db: Session = Depends(get_db), character_repo: CharacterRepository = Depends(get_character_repo)):
    """删除角色"""
    character = character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    db.delete(character)
    db.commit()
    
    return {"success": True, "message": "删除成功"}


@router.delete("/")
async def delete_characters_by_novel(novel_id: str = Query(..., description="小说ID"), db: Session = Depends(get_db), novel_repo: NovelRepository = Depends(get_novel_repo)):
    """删除指定小说的所有角色"""
    # 检查小说是否存在
    novel = novel_repo.get_by_id(novel_id)
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
async def clear_characters_dir(novel_id: str = Query(..., description="小说ID"), novel_repo: NovelRepository = Depends(get_novel_repo)):
    """清空小说的角色图片目录（用于批量重新生成前）"""
    # 检查小说是否存在
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 清空角色图片目录
    from app.services.file_storage import file_storage
    success = file_storage.delete_characters_dir(novel_id)
    
    if success:
        return {"success": True, "message": "角色图片目录已清空"}
    else:
        raise HTTPException(status_code=500, detail="清空角色图片目录失败")



@router.get("/{character_id}/prompt", response_model=dict)
async def get_character_prompt(character_id: str, db: Session = Depends(get_db), novel_repo: NovelRepository = Depends(get_novel_repo), character_repo: CharacterRepository = Depends(get_character_repo)):
    """获取角色生成时使用的拼接后提示词"""
    character = character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 获取角色所属小说
    novel = novel_repo.get_by_id(character.novel_id)
    
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


@router.post("/{character_id}/generate-appearance", response_model=dict)
async def generate_appearance(
    character_id: str,
    db: Session = Depends(get_db),
    character_repo: CharacterRepository = Depends(get_character_repo)
):
    """使用 DeepSeek AI 智能生成角色外貌描述"""
    character = character_repo.get_by_id(character_id)
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

