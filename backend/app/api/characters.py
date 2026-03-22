"""
角色路由 - 角色 CRUD 和图像生成相关接口
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.utils.time_utils import format_datetime
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.services.prompt_builder import build_character_prompt, get_style
from app.services.character_service import CharacterService
from app.repositories import NovelRepository, CharacterRepository, PromptTemplateRepository, TaskRepository
from app.schemas.character import CharacterCreate, CharacterUpdate
from app.api.deps import get_novel_repo, get_character_repo, get_prompt_template_repo, get_llm_service, get_task_repo

router = APIRouter()
settings = get_settings()
comfyui_service = ComfyUIService()


@router.get("/", response_model=dict)
async def list_characters(
    novel_id: str = None, 
    novel_repo: NovelRepository = Depends(get_novel_repo), 
    character_repo: CharacterRepository = Depends(get_character_repo)
):
    """获取角色列表"""
    if novel_id:
        characters = character_repo.list_by_novel(novel_id)
    else:
        characters = character_repo.list_all()
    
    # 批量预加载小说信息，避免 N+1 查询
    novel_ids = {c.novel_id for c in characters if c.novel_id}
    novels_map = {}
    for nid in novel_ids:
        novel = novel_repo.get_by_id(nid)
        if novel:
            novels_map[nid] = novel
    
    result = []
    for c in characters:
        novel = novels_map.get(c.novel_id)
        result.append({
            "id": c.id,
            "novelId": c.novel_id,
            "name": c.name,
            "description": c.description,
            "appearance": c.appearance,
            "voicePrompt": c.voice_prompt,
            "referenceAudioUrl": c.reference_audio_url,
            "imageUrl": c.image_url,
            "generatingStatus": c.generating_status,
            "portraitTaskId": c.portrait_task_id,
            "novelName": novel.title if novel else None,
            "startChapter": c.start_chapter,
            "endChapter": c.end_chapter,
            "isIncremental": c.is_incremental,
            "isNarrator": c.is_narrator or False,
            "sourceRange": c.source_range,
            "lastParsedAt": format_datetime(c.last_parsed_at),
            "createdAt": format_datetime(c.created_at),
            "updatedAt": format_datetime(c.updated_at),
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
            "voicePrompt": character.voice_prompt,
            "referenceAudioUrl": character.reference_audio_url,
            "imageUrl": character.image_url,
            "generatingStatus": character.generating_status,
            "portraitTaskId": character.portrait_task_id,
            "novelName": novel.title if novel else None,
            "startChapter": character.start_chapter,
            "endChapter": character.end_chapter,
            "isIncremental": character.is_incremental,
            "isNarrator": character.is_narrator or False,
            "sourceRange": character.source_range,
            "lastParsedAt": format_datetime(character.last_parsed_at),
            "createdAt": format_datetime(character.created_at),
            "updatedAt": format_datetime(character.updated_at),
        }
    }


@router.post("/", response_model=dict)
async def create_character(
    data: CharacterCreate,
    character_repo: CharacterRepository = Depends(get_character_repo),
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """创建角色"""
    # 验证小说存在
    novel = novel_repo.get_by_id(data.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    character = character_repo.create_from_schema(
        novel_id=data.novel_id,
        name=data.name,
        description=data.description or "",
        appearance=data.appearance or ""
    )
    
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
            "createdAt": format_datetime(character.created_at),
        }
    }


@router.put("/{character_id}", response_model=dict)
async def update_character(
    character_id: str,
    data: CharacterUpdate,
    character_repo: CharacterRepository = Depends(get_character_repo),
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """更新角色"""
    character = character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    character = character_repo.update_from_schema(
        character=character,
        name=data.name,
        description=data.description,
        appearance=data.appearance,
        voice_prompt=data.voice_prompt
    )
    
    novel = novel_repo.get_by_id(character.novel_id)
    
    return {
        "success": True,
        "data": {
            "id": character.id,
            "novelId": character.novel_id,
            "name": character.name,
            "description": character.description,
            "appearance": character.appearance,
            "voicePrompt": character.voice_prompt,
            "imageUrl": character.image_url,
            "novelName": novel.title if novel else None,
            "updatedAt": format_datetime(character.updated_at),
        }
    }


@router.delete("/{character_id}")
async def delete_character(character_id: str, character_repo: CharacterRepository = Depends(get_character_repo)):
    """删除角色"""
    character = character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 不允许删除旁白角色
    if character.is_narrator:
        raise HTTPException(status_code=400, detail="旁白角色不可删除")

    character_repo.delete(character)

    return {"success": True, "message": "删除成功"}


@router.delete("/")
async def delete_characters_by_novel(
    novel_id: str = Query(..., description="小说ID"), 
    novel_repo: NovelRepository = Depends(get_novel_repo),
    character_repo: CharacterRepository = Depends(get_character_repo)
):
    """删除指定小说的所有角色"""
    # 检查小说是否存在
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 删除该小说的所有角色
    result = character_repo.delete_by_novel(novel_id)
    
    # 删除角色图片目录
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
    success = file_storage.delete_characters_dir(novel_id)
    
    if success:
        return {"success": True, "message": "角色图片目录已清空"}
    else:
        raise HTTPException(status_code=500, detail="清空角色图片目录失败")



@router.get("/{character_id}/prompt", response_model=dict)
async def get_character_prompt(
    character_id: str,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    character_repo: CharacterRepository = Depends(get_character_repo),
    prompt_template_repo: PromptTemplateRepository = Depends(get_prompt_template_repo)
):
    """获取角色生成时使用的拼接后提示词"""
    character = character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 获取角色所属小说
    novel = novel_repo.get_by_id(character.novel_id)

    # 获取提示词模板
    template = None
    if novel and novel.prompt_template_id:
        template = prompt_template_repo.get_by_id(novel.prompt_template_id)

    # 如果没有指定模板，使用默认系统模板
    if not template:
        template = prompt_template_repo.get_first_system_template()

    # 获取风格提示词
    style, style_template = get_style(db, novel, "character")

    # 构建提示词
    prompt = build_character_prompt(
        name=character.name,
        appearance=character.appearance,
        description=character.description,
        template=template.template if template else None,
        style=style
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
        character_repo.update_appearance(character, appearance)
        
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


@router.post("/{character_id}/generate-portrait", response_model=dict)
async def generate_character_portrait(
    character_id: str,
    db: Session = Depends(get_db)
):
    """生成角色人设图任务"""
    character_service = CharacterService(db)
    return character_service.create_character_portrait_task(character_id)


@router.post("/{character_id}/upload-image", response_model=dict)
async def upload_character_image(
    character_id: str,
    file: UploadFile = File(...),
    character_repo: CharacterRepository = Depends(get_character_repo),
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """
    上传角色图片
    
    支持用户从本地上传角色形象图片，替代AI生成
    """
    character = character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 验证文件类型
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400, 
            detail=f"不支持的文件类型: {file.content_type}，仅支持 PNG, JPG, WEBP"
        )
    
    try:
        # 获取保存路径
        file_path = file_storage.get_character_image_path(
            novel_id=character.novel_id,
            character_name=character.name
        )
        
        # 保存文件
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 计算访问URL
        relative_path = file_path.relative_to(file_storage.base_dir)
        image_url = f"/api/files/{relative_path}"
        
        # 更新角色记录
        character_repo.update_image(character, image_url)
        
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
                "novelName": novel.title if novel else None,
                "updatedAt": character.updated_at.isoformat() if character.updated_at else None,
            },
            "message": "图片上传成功"
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.post("/{character_id}/upload-audio", response_model=dict)
async def upload_character_audio(
    character_id: str,
    file: UploadFile = File(...),
    character_repo: CharacterRepository = Depends(get_character_repo),
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """
    上传角色参考音频

    支持用户从本地上传音频文件作为角色参考音色
    支持格式: MP3, WAV, FLAC, OGG, M4A
    最大文件大小: 10MB
    """
    character = character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 验证文件类型
    allowed_types = ["audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
                     "audio/flac", "audio/x-flac", "audio/ogg", "audio/x-ogg",
                     "audio/mp4", "audio/x-m4a", "audio/m4a"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}，仅支持 MP3, WAV, FLAC, OGG, M4A"
        )

    # 验证文件大小 (10MB)
    content = await file.read()
    max_size = 10 * 1024 * 1024  # 10MB
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制，最大支持 10MB，当前文件大小: {len(content) / 1024 / 1024:.2f}MB"
        )

    try:
        # 获取文件扩展名
        ext = ".mp3"
        if file.filename:
            filename_lower = file.filename.lower()
            if filename_lower.endswith(".wav"):
                ext = ".wav"
            elif filename_lower.endswith(".flac"):
                ext = ".flac"
            elif filename_lower.endswith(".ogg"):
                ext = ".ogg"
            elif filename_lower.endswith(".m4a"):
                ext = ".m4a"

        # 保存文件
        file_path = file_storage.save_uploaded_audio_file(
            novel_id=character.novel_id,
            character_name=character.name,
            content=content,
            ext=ext
        )

        # 计算访问URL
        relative_path = file_path.relative_to(file_storage.base_dir)
        audio_url = f"/api/files/{relative_path}"

        # 更新角色记录
        character_repo.update_reference_audio(character, audio_url)

        novel = novel_repo.get_by_id(character.novel_id)

        return {
            "success": True,
            "data": {
                "id": character.id,
                "novelId": character.novel_id,
                "name": character.name,
                "referenceAudioUrl": character.reference_audio_url,
                "novelName": novel.title if novel else None,
                "updatedAt": character.updated_at.isoformat() if character.updated_at else None,
            },
            "message": "音频上传成功"
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


# ==================== 音色生成相关接口 ====================

@router.post("/{character_id}/generate-voice", response_model=dict)
async def generate_character_voice(
    character_id: str,
    db: Session = Depends(get_db)
):
    """生成角色音色任务"""
    character_service = CharacterService(db)
    return character_service.create_character_voice_task(character_id)


@router.get("/{character_id}/voice/status", response_model=dict)
async def get_voice_generation_status(
    character_id: str,
    task_repo: TaskRepository = Depends(get_task_repo),
    character_repo: CharacterRepository = Depends(get_character_repo)
):
    """获取角色音色生成任务状态"""
    character = character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 查找进行中的音色生成任务
    active_task = task_repo.get_active_by_character_and_type(character_id, "character_voice")

    if active_task:
        return {
            "success": True,
            "data": {
                "status": active_task.status,
                "taskId": active_task.id,
                "progress": active_task.progress or 0,
                "message": active_task.error_message or "",
                "referenceAudioUrl": None
            }
        }

    # 如果没有进行中的任务，返回当前音频URL
    return {
        "success": True,
        "data": {
            "status": "idle",
            "taskId": None,
            "progress": 0,
            "message": "",
            "referenceAudioUrl": character.reference_audio_url
        }
    }

