import json
import asyncio
import httpx
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.novel import Novel, Chapter, Character
from app.models.prompt_template import PromptTemplate
from app.models.task import Task
from app.schemas.novel import NovelCreate, NovelResponse, ChapterCreate, ChapterResponse
from app.services.llm_service import LLMService
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.api.tasks import validate_workflow_node_mapping
from app.repositories import NovelRepository, ChapterRepository, CharacterRepository, SceneRepository

# 注意：不要在模块级别创建 LLMService 实例
# 因为配置可能在运行时更新，每次使用时应创建新实例
comfyui_service = ComfyUIService()


def get_llm_service() -> LLMService:
    """获取 LLMService 实例（每次调用创建新实例以获取最新配置）"""
    return LLMService()


def get_novel_repo(db: Session = Depends(get_db)) -> NovelRepository:
    """获取 NovelRepository 实例"""
    return NovelRepository(db)


def get_chapter_repo(db: Session = Depends(get_db)) -> ChapterRepository:
    """获取 ChapterRepository 实例"""
    return ChapterRepository(db)


def get_character_repo(db: Session = Depends(get_db)) -> CharacterRepository:
    """获取 CharacterRepository 实例"""
    return CharacterRepository(db)


def get_scene_repo(db: Session = Depends(get_db)) -> SceneRepository:
    """获取 SceneRepository 实例"""
    return SceneRepository(db)


router = APIRouter()


@router.get("/", response_model=dict)
async def list_novels(novel_repo: NovelRepository = Depends(get_novel_repo)):
    """获取小说列表"""
    result = novel_repo.list_with_cover()
    return {
        "success": True,
        "data": result
    }


@router.post("/", response_model=dict)
async def create_novel(novel: NovelCreate, db: Session = Depends(get_db)):
    """创建新小说"""
    # 如果没有指定提示词模板，使用默认系统模板
    prompt_template_id = novel.prompt_template_id
    if not prompt_template_id:
        default_template = db.query(PromptTemplate).filter(
            PromptTemplate.is_system == True
        ).order_by(PromptTemplate.created_at.asc()).first()
        if default_template:
            prompt_template_id = default_template.id
    
    db_novel = Novel(
        title=novel.title,
        author=novel.author,
        description=novel.description,
        prompt_template_id=prompt_template_id,
        chapter_split_prompt_template_id=novel.chapter_split_prompt_template_id,
        aspect_ratio=novel.aspect_ratio or "16:9",
    )
    db.add(db_novel)
    db.commit()
    db.refresh(db_novel)
    return {
        "success": True,
        "data": {
            "id": db_novel.id,
            "title": db_novel.title,
            "author": db_novel.author,
            "description": db_novel.description,
            "cover": db_novel.cover,
            "status": db_novel.status,
            "chapterCount": db_novel.chapter_count,
            "promptTemplateId": db_novel.prompt_template_id,
            "chapterSplitPromptTemplateId": db_novel.chapter_split_prompt_template_id,
            "aspectRatio": db_novel.aspect_ratio or "16:9",
            "createdAt": db_novel.created_at.isoformat() if db_novel.created_at else None,
        }
    }


@router.get("/{novel_id}", response_model=dict)
async def get_novel(novel_id: str, novel_repo: NovelRepository = Depends(get_novel_repo)):
    """获取小说详情"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {
        "success": True,
        "data": {
            "id": novel.id,
            "title": novel.title,
            "author": novel.author,
            "description": novel.description,
            "cover": novel.cover,
            "status": novel.status,
            "chapterCount": novel.chapter_count,
            "promptTemplateId": novel.prompt_template_id,
            "chapterSplitPromptTemplateId": novel.chapter_split_prompt_template_id,
            "aspectRatio": novel.aspect_ratio or "16:9",
            "createdAt": novel.created_at.isoformat() if novel.created_at else None,
        }
    }


@router.put("/{novel_id}", response_model=dict)
async def update_novel(novel_id: str, data: dict, db: Session = Depends(get_db), novel_repo: NovelRepository = Depends(get_novel_repo)):
    """更新小说信息"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 更新字段
    if "title" in data:
        novel.title = data["title"]
    if "author" in data:
        novel.author = data["author"]
    if "description" in data:
        novel.description = data["description"]
    if "promptTemplateId" in data:
        novel.prompt_template_id = data["promptTemplateId"]
    if "chapterSplitPromptTemplateId" in data:
        novel.chapter_split_prompt_template_id = data["chapterSplitPromptTemplateId"]
    if "aspectRatio" in data:
        novel.aspect_ratio = data["aspectRatio"]
    
    db.commit()
    db.refresh(novel)
    
    return {
        "success": True,
        "data": {
            "id": novel.id,
            "title": novel.title,
            "author": novel.author,
            "description": novel.description,
            "cover": novel.cover,
            "status": novel.status,
            "chapterCount": novel.chapter_count,
            "promptTemplateId": novel.prompt_template_id,
            "chapterSplitPromptTemplateId": novel.chapter_split_prompt_template_id,
            "aspectRatio": novel.aspect_ratio or "16:9",
            "createdAt": novel.created_at.isoformat() if novel.created_at else None,
            "updatedAt": novel.updated_at.isoformat() if novel.updated_at else None,
        }
    }


@router.delete("/{novel_id}")
async def delete_novel(novel_id: str, db: Session = Depends(get_db), novel_repo: NovelRepository = Depends(get_novel_repo)):
    """删除小说"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    db.delete(novel)
    db.commit()
    
    return {"success": True, "message": "删除成功"}


@router.post("/{novel_id}/parse", response_model=dict)
async def parse_novel(novel_id: str, db: Session = Depends(get_db), novel_repo: NovelRepository = Depends(get_novel_repo), chapter_repo: ChapterRepository = Depends(get_chapter_repo)):
    """解析小说内容，提取角色和场景"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 获取所有章节内容
    chapters = chapter_repo.list_by_novel(novel_id)
    full_text = "\n\n".join([c.content for c in chapters if c.content])
    
    # 更新状态为解析中
    novel.status = "processing"
    db.commit()
    
    # 异步解析
    async def do_parse():
        try:
            result = await get_llm_service().parse_novel_text(full_text)
            
            # 保存解析结果到各个章节
            for chapter in chapters:
                if chapter.content:
                    chapter.parsed_data = result
            
            novel.status = "completed"
            db.commit()
        except Exception as e:
            novel.status = "failed"
            db.commit()
    
    # 使用 asyncio.create_task 实现真正并发
    import asyncio
    asyncio.create_task(do_parse())
    
    return {"success": True, "message": "解析任务已启动"}


@router.post("/{novel_id}/parse-characters/", response_model=dict)
async def parse_characters(
    novel_id: str, 
    sync: bool = False,
    start_chapter: int = None,
    end_chapter: int = None,
    is_incremental: bool = False,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    character_repo: CharacterRepository = Depends(get_character_repo)
):
    """解析小说内容，自动提取角色信息（支持章节范围和增量更新）"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 获取指定章节范围的章节
    chapters = chapter_repo.get_by_range(novel_id, start_chapter, end_chapter)
    
    if not chapters:
        return {"success": False, "message": "指定章节范围内没有内容"}
    
    # 构造章节范围描述
    source_range = None
    if start_chapter is not None or end_chapter is not None:
        start_desc = f"第{start_chapter}章" if start_chapter is not None else "第1章"
        end_desc = f"第{end_chapter}章" if end_chapter is not None else f"第{chapters[-1].number}章"
        source_range = f"{start_desc}至{end_desc}"
    
    full_text = "\n\n".join([c.content for c in chapters if c.content])
    if not full_text.strip():
        return {"success": False, "message": "章节内容为空"}
    
    try:
        # 调用 LLM 解析文本提取角色
        result = await get_llm_service().parse_novel_text(full_text, novel_id=novel_id, source_range=source_range)
        
        if "error" in result:
            return {"success": False, "message": f"解析失败: {result['error']}"}
        
        characters_data = result.get("characters", [])
        if not characters_data:
            return {"success": True, "data": [], "message": "未识别到角色"}
        
        # 创建角色记录
        created_characters = []
        updated_characters = []
        
        for char_data in characters_data:
            name = char_data.get("name", "").strip()
            if not name:
                continue
            
            # 检查是否已存在
            existing = character_repo.get_by_name(novel_id, name)
            
            if existing:
                # 增量更新模式：保留原有信息，只更新新解析的信息
                if is_incremental:
                    # 只更新空字段或补充更多信息
                    if not existing.description and char_data.get("description"):
                        existing.description = char_data.get("description")
                    if not existing.appearance and char_data.get("appearance"):
                        existing.appearance = char_data.get("appearance")
                    # 更新章节范围信息
                    if source_range:
                        if existing.source_range:
                            existing.source_range += f", {source_range}"
                        else:
                            existing.source_range = source_range
                else:
                    # 全量更新模式：直接覆盖
                    existing.description = char_data.get("description", existing.description)
                    existing.appearance = char_data.get("appearance", existing.appearance)
                    existing.source_range = source_range
                
                existing.last_parsed_at = datetime.utcnow()
                updated_characters.append(existing)
            else:
                # 创建新角色
                character = Character(
                    novel_id=novel_id,
                    name=name,
                    description=char_data.get("description", ""),
                    appearance=char_data.get("appearance", ""),
                    start_chapter=start_chapter,
                    end_chapter=end_chapter,
                    is_incremental=is_incremental,
                    source_range=source_range,
                    last_parsed_at=datetime.utcnow()
                )
                db.add(character)
                created_characters.append(character)
        
        db.commit()
        
        # 刷新对象以获取 ID
        for char in created_characters + updated_characters:
            db.refresh(char)
        
        # 构造响应消息
        message_parts = []
        if created_characters:
            message_parts.append(f"新增 {len(created_characters)} 个角色")
        if updated_characters:
            message_parts.append(f"更新 {len(updated_characters)} 个角色")
        
        return {
            "success": True,
            "data": [
                {
                    "id": c.id,
                    "name": c.name,
                    "description": c.description,
                    "appearance": c.appearance,
                    "startChapter": c.start_chapter,
                    "endChapter": c.end_chapter,
                    "isIncremental": c.is_incremental,
                    "sourceRange": c.source_range,
                    "lastParsedAt": c.last_parsed_at.isoformat() if c.last_parsed_at else None
                }
                for c in created_characters + updated_characters
            ],
            "message": "，".join(message_parts) if message_parts else "未识别到角色",
            "statistics": {
                "created": len(created_characters),
                "updated": len(updated_characters),
                "total": len(created_characters) + len(updated_characters)
            }
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "message": f"解析异常: {str(e)}"}


@router.post("/{novel_id}/chapters/{chapter_id}/parse-characters/", response_model=dict)
async def parse_chapter_characters(
    novel_id: str,
    chapter_id: str,
    is_incremental: bool = True,  # 默认为增量更新
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    character_repo: CharacterRepository = Depends(get_character_repo)
):
    """解析单章节内容，提取角色信息（支持增量更新）"""
    # 验证小说和章节
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    if not chapter.content:
        return {"success": False, "message": "章节内容为空"}
    
    try:
        # 调用 LLM 解析文本提取角色
        source_range = f"第{chapter.number}章"
        result = await get_llm_service().parse_novel_text(chapter.content, novel_id=novel_id, source_range=source_range)
        
        if "error" in result:
            return {"success": False, "message": f"解析失败: {result['error']}"}
        
        characters_data = result.get("characters", [])
        if not characters_data:
            return {"success": True, "data": [], "message": "未识别到角色"}
        
        # 创建角色记录
        created_characters = []
        updated_characters = []
        
        for char_data in characters_data:
            name = char_data.get("name", "").strip()
            if not name:
                continue
            
            # 检查是否已存在
            existing = character_repo.get_by_name(novel_id, name)
            
            source_range = f"第{chapter.number}章"
            
            if existing:
                # 增量更新模式：保留原有信息，只更新新解析的信息
                if is_incremental:
                    # 只更新空字段或补充更多信息
                    if not existing.description and char_data.get("description"):
                        existing.description = char_data.get("description")
                    if not existing.appearance and char_data.get("appearance"):
                        existing.appearance = char_data.get("appearance")
                    # 更新章节范围信息
                    if existing.source_range:
                        existing.source_range += f", {source_range}"
                    else:
                        existing.source_range = source_range
                else:
                    # 全量更新模式：直接覆盖
                    existing.description = char_data.get("description", existing.description)
                    existing.appearance = char_data.get("appearance", existing.appearance)
                    existing.source_range = source_range
                
                existing.last_parsed_at = datetime.utcnow()
                updated_characters.append(existing)
            else:
                # 创建新角色
                character = Character(
                    novel_id=novel_id,
                    name=name,
                    description=char_data.get("description", ""),
                    appearance=char_data.get("appearance", ""),
                    start_chapter=chapter.number,
                    end_chapter=chapter.number,
                    is_incremental=is_incremental,
                    source_range=source_range,
                    last_parsed_at=datetime.utcnow()
                )
                db.add(character)
                created_characters.append(character)
        
        db.commit()
        
        # 刷新对象以获取 ID
        for char in created_characters + updated_characters:
            db.refresh(char)
        
        # 构造响应消息
        message_parts = []
        if created_characters:
            message_parts.append(f"新增 {len(created_characters)} 个角色")
        if updated_characters:
            message_parts.append(f"更新 {len(updated_characters)} 个角色")
        
        return {
            "success": True,
            "data": [
                {
                    "id": c.id,
                    "name": c.name,
                    "description": c.description,
                    "appearance": c.appearance,
                    "startChapter": c.start_chapter,
                    "endChapter": c.end_chapter,
                    "isIncremental": c.is_incremental,
                    "sourceRange": c.source_range,
                    "lastParsedAt": c.last_parsed_at.isoformat() if c.last_parsed_at else None
                }
                for c in created_characters + updated_characters
            ],
            "message": "，".join(message_parts) if message_parts else "未识别到角色",
            "statistics": {
                "created": len(created_characters),
                "updated": len(updated_characters),
                "total": len(created_characters) + len(updated_characters)
            }
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "message": f"解析异常: {str(e)}"}


@router.post("/{novel_id}/chapters/{chapter_id}/parse-scenes/", response_model=dict)
async def parse_chapter_scenes(
    novel_id: str,
    chapter_id: str,
    is_incremental: bool = True,  # 默认为增量更新
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    scene_repo: SceneRepository = Depends(get_scene_repo)
):
    """解析单章节内容，提取场景信息（支持增量更新）"""
    from app.models.novel import Scene
    
    # 验证小说和章节
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    if not chapter.content:
        return {"success": False, "message": "章节内容为空"}
    
    # 获取场景解析提示词模板
    template = db.query(PromptTemplate).filter(
        PromptTemplate.type == 'scene_parse',
        PromptTemplate.is_system == True
    ).order_by(PromptTemplate.created_at.asc()).first()
    
    prompt_template = template.template if template else None
    
    try:
        source_range = f"第{chapter.number}章"
        
        # 调用 LLM 解析场景
        result = await get_llm_service().parse_scenes(
            novel_id=novel_id,
            chapter_content=chapter.content[:20000],  # 限制长度
            chapter_title=source_range,
            prompt_template=prompt_template
        )
        
        if result.get("error"):
            return {"success": False, "message": result["error"]}
        
        scenes_data = result.get("scenes", [])
        
        # 获取现有场景
        existing_scene_names = scene_repo.get_dict_by_novel(novel_id)
        
        created_scenes = []
        updated_scenes = []
        
        for scene_data in scenes_data:
            name = scene_data.get("name", "")
            if not name:
                continue
            
            if name in existing_scene_names:
                # 更新现有场景
                existing = existing_scene_names[name]
                
                # 增量更新模式：保留原有信息，只更新新解析的信息
                if is_incremental:
                    if not existing.description and scene_data.get("description"):
                        existing.description = scene_data.get("description")
                    if not existing.setting and scene_data.get("setting"):
                        existing.setting = scene_data.get("setting")
                    # 更新章节范围信息
                    if existing.source_range:
                        if source_range not in existing.source_range:
                            existing.source_range += f", {source_range}"
                    else:
                        existing.source_range = source_range
                else:
                    # 全量更新模式
                    existing.description = scene_data.get("description", existing.description)
                    existing.setting = scene_data.get("setting", existing.setting)
                    existing.source_range = source_range
                
                existing.is_incremental = is_incremental
                existing.last_parsed_at = datetime.utcnow()
                updated_scenes.append(existing)
            else:
                # 创建新场景
                scene = Scene(
                    novel_id=novel_id,
                    name=name,
                    description=scene_data.get("description", ""),
                    setting=scene_data.get("setting", ""),
                    start_chapter=chapter.number,
                    end_chapter=chapter.number,
                    is_incremental=is_incremental,
                    source_range=source_range,
                    last_parsed_at=datetime.utcnow()
                )
                db.add(scene)
                created_scenes.append(scene)
        
        db.commit()
        
        # 刷新对象
        for s in created_scenes + updated_scenes:
            db.refresh(s)
        
        # 构造响应消息
        message_parts = []
        if created_scenes:
            message_parts.append(f"新增 {len(created_scenes)} 个场景")
        if updated_scenes:
            message_parts.append(f"更新 {len(updated_scenes)} 个场景")
        
        return {
            "success": True,
            "data": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "setting": s.setting,
                    "startChapter": s.start_chapter,
                    "endChapter": s.end_chapter,
                    "isIncremental": s.is_incremental,
                    "sourceRange": s.source_range,
                    "lastParsedAt": s.last_parsed_at.isoformat() if s.last_parsed_at else None
                }
                for s in created_scenes + updated_scenes
            ],
            "message": "，".join(message_parts) if message_parts else "未识别到场景",
            "statistics": {
                "created": len(created_scenes),
                "updated": len(updated_scenes),
                "total": len(created_scenes) + len(updated_scenes)
            }
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "message": f"解析异常: {str(e)}"}


@router.get("/{novel_id}/chapters", response_model=dict)
async def list_chapters(novel_id: str, novel_repo: NovelRepository = Depends(get_novel_repo), chapter_repo: ChapterRepository = Depends(get_chapter_repo)):
    """获取章节列表"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapters = chapter_repo.list_by_novel(novel_id)
    return {
        "success": True,
        "data": [
            {
                "id": c.id,
                "number": c.number,
                "title": c.title,
                "status": c.status,
                "progress": c.progress,
                "createdAt": c.created_at.isoformat() if c.created_at else None,
            }
            for c in chapters
        ]
    }


@router.post("/{novel_id}/chapters", response_model=dict)
async def create_chapter(novel_id: str, data: dict, db: Session = Depends(get_db), novel_repo: NovelRepository = Depends(get_novel_repo), chapter_repo: ChapterRepository = Depends(get_chapter_repo)):
    """创建章节"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapter = Chapter(
        novel_id=novel_id,
        number=data.get("number", 1),
        title=data["title"],
        content=data.get("content", ""),
    )
    db.add(chapter)
    
    # 更新章节数
    novel.chapter_count = len(chapter_repo.list_by_novel(novel_id)) + 1
    
    db.commit()
    db.refresh(chapter)
    
    return {
        "success": True,
        "data": {
            "id": chapter.id,
            "number": chapter.number,
            "title": chapter.title,
            "status": chapter.status,
            "progress": chapter.progress,
            "createdAt": chapter.created_at.isoformat() if chapter.created_at else None,
        }
    }


@router.get("/{novel_id}/chapters/{chapter_id}", response_model=dict)
async def get_chapter(novel_id: str, chapter_id: str, chapter_repo: ChapterRepository = Depends(get_chapter_repo)):
    """获取章节详情"""
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    import json
    
    # 解析 JSON 字段
    character_images = json.loads(chapter.character_images) if chapter.character_images else []
    shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
    shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
    transition_videos = json.loads(chapter.transition_videos) if chapter.transition_videos else {}
    
    return {
        "success": True,
        "data": {
            "id": chapter.id,
            "number": chapter.number,
            "title": chapter.title,
            "content": chapter.content,
            "status": chapter.status,
            "progress": chapter.progress,
            "parsedData": chapter.parsed_data,
            "characterImages": character_images,
            "shotImages": shot_images,
            "shotVideos": shot_videos,
            "transitionVideos": transition_videos,
            "finalVideo": chapter.final_video,
            "createdAt": chapter.created_at.isoformat() if chapter.created_at else None,
        }
    }


@router.put("/{novel_id}/chapters/{chapter_id}", response_model=dict)
async def update_chapter(
    novel_id: str, 
    chapter_id: str, 
    data: dict, 
    db: Session = Depends(get_db),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo)
):
    """更新章节"""
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    if "title" in data:
        chapter.title = data["title"]
    if "content" in data:
        chapter.content = data["content"]
    if "parsedData" in data:
        chapter.parsed_data = data["parsedData"]
    
    db.commit()
    db.refresh(chapter)
    
    return {
        "success": True,
        "data": {
            "id": chapter.id,
            "number": chapter.number,
            "title": chapter.title,
            "content": chapter.content,
            "status": chapter.status,
            "progress": chapter.progress,
            "parsedData": chapter.parsed_data,
            "createdAt": chapter.created_at.isoformat() if chapter.created_at else None,
            "updatedAt": chapter.updated_at.isoformat() if chapter.updated_at else None,
        }
    }


@router.delete("/{novel_id}/chapters/{chapter_id}")
async def delete_chapter(novel_id: str, chapter_id: str, db: Session = Depends(get_db), novel_repo: NovelRepository = Depends(get_novel_repo), chapter_repo: ChapterRepository = Depends(get_chapter_repo)):
    """删除章节"""
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    db.delete(chapter)
    
    # 更新小说章节数
    novel = novel_repo.get_by_id(novel_id)
    if novel:
        novel.chapter_count = len(chapter_repo.list_by_novel(novel_id)) - 1
    
    db.commit()
    
    return {"success": True, "message": "删除成功"}


@router.post("/{novel_id}/chapters/{chapter_id}/split", response_model=dict)
async def split_chapter(
    novel_id: str, 
    chapter_id: str, 
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    character_repo: CharacterRepository = Depends(get_character_repo),
    scene_repo: SceneRepository = Depends(get_scene_repo)
):
    """
    使用小说配置的拆分提示词将章节拆分为分镜
    """
    # 获取章节
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 获取小说
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 检查 LLM 配置
    llm_service = get_llm_service()
    if not llm_service.api_key and llm_service.provider != "ollama":
        return {
            "success": False,
            "data": {
                "error": "LLM API Key 未配置，请在系统设置中配置 API Key",
                "chapter": chapter.title,
                "characters": [],
                "scenes": [],
                "shots": []
            }
        }
    
    if not llm_service.api_url:
        return {
            "success": False,
            "data": {
                "error": "LLM API URL 未配置，请在系统设置中配置 API URL",
                "chapter": chapter.title,
                "characters": [],
                "scenes": [],
                "shots": []
            }
        }
    
    # 获取拆分提示词模板
    prompt_template = None
    if novel.chapter_split_prompt_template_id:
        prompt_template = db.query(PromptTemplate).filter(
            PromptTemplate.id == novel.chapter_split_prompt_template_id
        ).first()
    
    # 如果没有配置，使用默认模板
    if not prompt_template:
        prompt_template = db.query(PromptTemplate).filter(
            PromptTemplate.type == "chapter_split",
            PromptTemplate.is_system == True
        ).first()
    
    if not prompt_template:
        raise HTTPException(status_code=400, detail="未找到章节拆分提示词模板")
    
    # 获取当前小说的所有角色列表
    character_names = character_repo.get_names_by_novel(novel_id)
    
    # 获取当前小说的所有场景列表
    from app.models.novel import Scene
    scene_names = scene_repo.get_names_by_novel(novel_id)
    
    # 获取小说配置的角色提示词模板 style，用于替换 {图像风格} 和 ##STYLE## 占位符
    style = "anime style, high quality, detailed"  # 默认风格
    if novel.prompt_template_id:
        character_prompt_template = db.query(PromptTemplate).filter(
            PromptTemplate.id == novel.prompt_template_id
        ).first()
        if character_prompt_template and character_prompt_template.template:
            try:
                import re
                # 尝试从模板中提取 style 字段
                template_data = json.loads(character_prompt_template.template)
                if isinstance(template_data, dict) and "style" in template_data:
                    style = template_data["style"]
                else:
                    style = character_prompt_template.template.replace("{appearance}", "").replace("{description}", "").strip(", ")
            except json.JSONDecodeError:
                style = character_prompt_template.template.replace("{appearance}", "").replace("{description}", "").strip(", ")
                style = re.sub(r',\s*,', ',', style)
                style = re.sub(r'\s+', ' ', style)
                style = style.strip(", ")
            print(f"[SplitChapter] Using style from character prompt template: {style}")
    
    # 调用 DeepSeek API 进行拆分，传递 style 参数和场景白名单
    result = await get_llm_service().split_chapter_with_prompt(
        chapter_title=chapter.title,
        chapter_content=chapter.content or "",
        prompt_template=prompt_template.template,
        word_count=50,
        character_names=character_names,
        scene_names=scene_names,
        style=style
    )
    
    # 保存解析结果到章节
    chapter.parsed_data = json.dumps(result, ensure_ascii=False)
    db.commit()
    
    return {
        "success": True,
        "data": result
    }


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/generate", response_model=dict)
async def generate_shot_image(
    novel_id: str,
    chapter_id: str,
    shot_index: int,  # 1-based index
    db: Session = Depends(get_db)
):
    """
    为指定分镜生成图片（创建后台任务）
    
    流程：
    1. 验证请求参数
    2. 创建任务记录
    3. 后台异步执行生成
    """
    from app.models.workflow import Workflow
    
    # 获取章节
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 获取小说
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 解析章节数据
    if not chapter.parsed_data:
        raise HTTPException(status_code=400, detail="章节未拆分，请先进行AI拆分")
    
    parsed_data = json.loads(chapter.parsed_data) if isinstance(chapter.parsed_data, str) else chapter.parsed_data
    shots = parsed_data.get("shots", [])
    
    if shot_index < 1 or shot_index > len(shots):
        raise HTTPException(status_code=400, detail="分镜索引超出范围")
    
    shot = shots[shot_index - 1]
    shot_description = shot.get("description", "")
    
    # 检查是否已有进行中的任务
    existing_task = db.query(Task).filter(
        Task.novel_id == novel_id,
        Task.chapter_id == chapter_id,
        Task.type == "shot_image",
        Task.name.like(f"%镜{shot_index}%"),
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
    
    # 获取激活的分镜生图工作流
    workflow = db.query(Workflow).filter(
        Workflow.type == "shot",
        Workflow.is_active == True
    ).first()
    
    if not workflow:
        raise HTTPException(status_code=400, detail="未配置分镜生图工作流")
    
    # 验证工作流节点映射配置
    is_valid, error_msg = validate_workflow_node_mapping(workflow, "shot")
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    # 清除旧的图片数据和文件，避免前端显示旧图
    # 1. 删除旧的分镜图文件
    file_storage.delete_shot_image(novel_id, chapter_id, shot_index)
    
    # 2. 清除 shot_images 数组中的记录
    shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
    if isinstance(shot_images, list) and len(shot_images) >= shot_index:
        shot_images[shot_index - 1] = None
        chapter.shot_images = json.dumps(shot_images, ensure_ascii=False)
    
    # 3. 同时清除 parsed_data 中的旧图片 URL
    if "shots" in parsed_data and len(parsed_data["shots"]) >= shot_index:
        if "image_url" in parsed_data["shots"][shot_index - 1]:
            del parsed_data["shots"][shot_index - 1]["image_url"]
        if "image_path" in parsed_data["shots"][shot_index - 1]:
            del parsed_data["shots"][shot_index - 1]["image_path"]
        chapter.parsed_data = json.dumps(parsed_data, ensure_ascii=False)
    
    db.commit()
    
    # 创建任务记录
    task = Task(
        type="shot_image",
        name=f"生成分镜图: 镜{shot_index}",
        description=f"为章节 '{chapter.title}' 的分镜 {shot_index} 生成图片",
        novel_id=novel_id,
        chapter_id=chapter_id,
        status="pending",
        workflow_id=workflow.id,
        workflow_name=workflow.name
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    
    print(f"[GenerateShot] Created task {task.id} for shot {shot_index}")
    
    # 使用 asyncio.create_task 实现真正的并发执行
    # 而不是使用 background_tasks（它是顺序执行的）
    asyncio.create_task(
        generate_shot_task(
            task.id,
            novel_id,
            chapter_id,
            shot_index,
            shot_description,
            workflow.id
        )
    )
    
    return {
        "success": True,
        "message": "分镜图生成任务已创建",
        "data": {
            "taskId": task.id,
            "status": "pending"
        }
    }


async def generate_shot_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    shot_description: str,
    workflow_id: str
):
    """
    后台任务：生成分镜图片
    """
    import os
    from PIL import Image, ImageDraw, ImageFont
    from app.models.workflow import Workflow
    from app.services.file_storage import file_storage
    from app.core.database import SessionLocal
    
    db = SessionLocal()
    try:
        # 获取任务
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        
        # 更新任务状态为运行中
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.current_step = "准备生成环境..."
        db.commit()
        
        # 获取章节和小说
        chapter = db.query(Chapter).filter(
            Chapter.id == chapter_id,
            Chapter.novel_id == novel_id
        ).first()
        
        if not chapter:
            task.status = "failed"
            task.error_message = "章节不存在"
            db.commit()
            return
        
        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        if not novel:
            task.status = "failed"
            task.error_message = "小说不存在"
            db.commit()
            return
        
        # 解析章节数据
        parsed_data = json.loads(chapter.parsed_data) if isinstance(chapter.parsed_data, str) else chapter.parsed_data
        shots = parsed_data.get("shots", [])
        
        if shot_index < 1 or shot_index > len(shots):
            task.status = "failed"
            task.error_message = "分镜索引超出范围"
            db.commit()
            return
        
        shot = shots[shot_index - 1]
        shot_characters = shot.get("characters", [])
        shot_scene = shot.get("scene", "")  # 获取场景信息
        
        print(f"[ShotTask {task_id}] Novel: {novel_id}, Chapter: {chapter_id}, Shot: {shot_index}")
        print(f"[ShotTask {task_id}] Description: {shot_description}")
        print(f"[ShotTask {task_id}] Characters: {shot_characters}")
        
        # 获取工作流
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            task.status = "failed"
            task.error_message = "工作流不存在"
            db.commit()
            return
        
        # 获取节点映射
        node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}
        print(f"[ShotTask {task_id}] Node mapping: {node_mapping}")
        
        # 先保存提示词
        task.prompt_text = shot_description
        db.commit()
        
        # 注意：实际提交的工作流会在调用ComfyUI后保存
        # 这里不保存原始模板，避免运行时看到错误数据
        
        # 获取小说配置的角色提示词模板 style
        style = "anime style, high quality, detailed"  # 默认风格
        if novel.prompt_template_id:
            prompt_template = db.query(PromptTemplate).filter(
                PromptTemplate.id == novel.prompt_template_id
            ).first()
            if prompt_template and prompt_template.template:
                # 解析模板内容获取 style
                try:
                    import re
                    # 尝试从模板中提取 style 字段（如果是 JSON 格式）
                    template_data = json.loads(prompt_template.template)
                    if isinstance(template_data, dict) and "style" in template_data:
                        style = template_data["style"]
                    else:
                        # 如果不是 JSON，则使用模板内容本身作为 style
                        style = prompt_template.template.replace("{appearance}", "").replace("{description}", "").strip(", ")
                except json.JSONDecodeError:
                    # 如果不是 JSON，则使用模板内容本身作为 style
                    style = prompt_template.template.replace("{appearance}", "").replace("{description}", "").strip(", ")
                    # 清理多余的逗号和空格
                    style = re.sub(r',\s*,', ',', style)  # 去掉多余逗号
                    style = re.sub(r'\s+', ' ', style)    # 多个空格变一个
                    style = style.strip(", ")
            print(f"[ShotTask {task_id}] Using style from prompt template: {style}")
        
        # 合并角色图片
        character_reference_path = None
        if shot_characters:
            task.current_step = f"合并角色图片: {', '.join(shot_characters)}"
            db.commit()
            
            # 获取角色图片路径
            character_images = []
            print(f"[ShotTask {task_id}] Looking for {len(shot_characters)} characters: {shot_characters}")
            for char_name in shot_characters:
                character = db.query(Character).filter(
                    Character.novel_id == novel_id,
                    Character.name == char_name
                ).first()
                print(f"[ShotTask {task_id}] Character '{char_name}': found={character is not None}, has_image={character.image_url if character else None}")
                if character and character.image_url:
                    # 从 URL 提取本地路径
                    char_path = character.image_url.replace("/api/files/", "")
                    # 处理已存储的错误格式（可能是反斜杠开头）
                    char_path = char_path.lstrip("\\/")
                    # 统一转换为正斜杠后分割
                    char_path = char_path.replace("\\", "/")
                    # 转换为系统路径格式
                    char_path_parts = char_path.split("/")
                    # 转换为绝对路径
                    full_path = os.path.join(os.path.dirname(__file__), "..", "..", "user_story", *char_path_parts)
                    full_path = os.path.abspath(full_path)
                    exists = os.path.exists(full_path)
                    print(f"[ShotTask {task_id}] Character '{char_name}': path={full_path}, exists={exists}")
                    if exists:
                        character_images.append((char_name, full_path))
                        print(f"[ShotTask {task_id}] Found character image: {char_name} -> {full_path}")
            
            print(f"[ShotTask {task_id}] Total character images found: {len(character_images)}")
            if character_images:
                # 创建合并图片目录 (chapter_{chapter_id}/merged_characters/)
                # 先删除旧的合并角色图（避免使用旧文件）
                # 包括旧的时间戳格式和可能的不同角色组合的 hash 格式
                story_dir = file_storage._get_story_dir(novel_id)
                chapter_short = chapter_id[:8] if chapter_id else "unknown"
                merged_dir = story_dir / f"chapter_{chapter_short}" / "merged_characters"
                if merged_dir.exists():
                    import glob
                    import re
                    # 删除该分镜的所有旧合并角色图（包括时间戳格式和 hash 格式）
                    old_files = glob.glob(str(merged_dir / f"shot_{shot_index:03d}_*_characters.png"))
                    for old_file in old_files:
                        try:
                            os.remove(old_file)
                            print(f"[ShotTask {task_id}] Removed old merged character image: {old_file}")
                        except Exception as e:
                            print(f"[ShotTask {task_id}] Failed to remove old file {old_file}: {e}")
                
                # 获取角色名列表（用于生成固定文件名）
                character_names = [name for name, _ in character_images]
                merged_path = file_storage.get_merged_characters_path(novel_id, chapter_id, shot_index, character_names)
                
                # 合并图片
                try:
                    # 计算布局
                    count = len(character_images)
                    if count == 1:
                        cols, rows = 1, 1
                    elif count <= 3:
                        cols, rows = 1, count
                    elif count == 4:
                        cols, rows = 2, 2
                    elif count <= 6:
                        cols, rows = 3, 2
                    else:
                        cols = 3
                        rows = (count + 2) // 3
                    
                    # 加载所有图片（不进行缩放，保持原图尺寸）
                    images = []
                    for char_name, img_path in character_images:
                        img = Image.open(img_path)
                        images.append((char_name, img))
                    
                    # 设置布局参数
                    name_height = 24  # 文字高度
                    padding = 15      # 外边距
                    img_spacing = 10  # 图片之间的间距
                    text_offset = 5   # 文字与图片的间距
                    
                    # 使用原图，不进行缩放
                    processed_images = [(char_name, img.copy()) for char_name, img in images]
                    
                    # 计算每列的最大宽度（用于对齐）
                    col_widths = []
                    for col in range(cols):
                        max_w = 0
                        for idx in range(col, len(processed_images), cols):
                            _, img = processed_images[idx]
                            max_w = max(max_w, img.width)
                        col_widths.append(max_w)
                    
                    # 计算每行的实际高度（取该行最高图片 + 文字高度）
                    row_heights = []
                    for row in range(rows):
                        max_h = 0
                        for idx in range(row * cols, min((row + 1) * cols, len(processed_images))):
                            _, img = processed_images[idx]
                            max_h = max(max_h, img.height)
                        row_heights.append(max_h + name_height + text_offset)
                    
                    # 计算画布尺寸
                    canvas_width = sum(col_widths) + (cols - 1) * img_spacing + 2 * padding
                    canvas_height = sum(row_heights) + 2 * padding
                    canvas = Image.new('RGB', (canvas_width, canvas_height), (255, 255, 255))
                    draw = ImageDraw.Draw(canvas)
                    
                    # 尝试加载中文字体（多平台支持）
                    font = None
                    font_paths = [
                        # macOS
                        "/System/Library/Fonts/PingFang.ttc",
                        "/System/Library/Fonts/STHeiti Light.ttc",
                        "/Library/Fonts/Arial Unicode.ttf",
                        # Windows
                        "C:/Windows/Fonts/simhei.ttf",
                        "C:/Windows/Fonts/simsun.ttc",
                        "C:/Windows/Fonts/msyh.ttc",
                        "C:/Windows/Fonts/msyhbd.ttc",
                        # Linux
                        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    ]
                    
                    for font_path in font_paths:
                        try:
                            font = ImageFont.truetype(font_path, 16)
                            print(f"[ShotTask {task_id}] Loaded font: {font_path}")
                            break
                        except:
                            continue
                    
                    if font is None:
                        font = ImageFont.load_default()
                        print(f"[ShotTask {task_id}] Warning: No Chinese font found, using default")
                    
                    # 绘制每个角色
                    current_y = padding
                    for idx, (char_name, img) in enumerate(processed_images):
                        col = idx % cols
                        row = idx // cols
                        
                        # 计算x坐标（基于列宽累加）
                        x = padding + sum(col_widths[:col]) + col * img_spacing
                        
                        # 计算y坐标（基于当前行的起始位置）
                        y = current_y
                        
                        # 在当前列宽度内居中放置图片
                        img_x = x + (col_widths[col] - img.width) // 2
                        img_y = y + (row_heights[row] - name_height - text_offset - img.height) // 2
                        canvas.paste(img, (img_x, img_y))
                        
                        # 绘制角色名称（在当前列宽度内居中）
                        text_bbox = draw.textbbox((0, 0), char_name, font=font)
                        text_width = text_bbox[2] - text_bbox[0]
                        text_x = x + (col_widths[col] - text_width) // 2
                        text_y = img_y + img.height + text_offset
                        draw.text((text_x, text_y), char_name, fill=(51, 51, 51), font=font)
                        
                        # 更新下一行的起始y坐标
                        if col == cols - 1 or idx == len(processed_images) - 1:
                            current_y += row_heights[row]
                    
                    # 保存合并图片
                    canvas.save(merged_path, "PNG")
                    character_reference_path = str(merged_path)
                    
                    # 构建合并角色图的 URL 并保存到 parsed_data
                    # 在 Windows 上，将反斜杠替换为正斜杠以构建 URL
                    merged_relative_path = str(merged_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
                    merged_url = f"/api/files/{merged_relative_path.lstrip('/')}"
                    
                    # 更新 parsed_data 中的合并角色图 URL
                    latest_parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {"shots": []}
                    if "shots" not in latest_parsed_data:
                        latest_parsed_data["shots"] = []
                    while len(latest_parsed_data["shots"]) < shot_index:
                        latest_parsed_data["shots"].append({})
                    latest_parsed_data["shots"][shot_index - 1]["merged_character_image"] = merged_url
                    chapter.parsed_data = json.dumps(latest_parsed_data, ensure_ascii=False)
                    
                    print(f"[ShotTask {task_id}] Merged character image saved: {merged_path}, URL: {merged_url}")
                    task.current_step = f"已合并 {len(character_images)} 个角色图片"
                    db.commit()
                    
                except Exception as e:
                    print(f"[ShotTask {task_id}] Failed to merge character images: {e}")
                    import traceback
                    traceback.print_exc()
                    task.current_step = "角色图片合并失败，继续生成..."
                    db.commit()
        
        # 处理场景图
        scene_reference_path = None
        if shot_scene:
            task.current_step = f"查找场景图: {shot_scene}"
            db.commit()
            
            # 在场景库中查找匹配的场景
            from app.models.novel import Scene
            scene = db.query(Scene).filter(
                Scene.novel_id == novel_id,
                Scene.name == shot_scene
            ).first()
            
            print(f"[ShotTask {task_id}] Scene '{shot_scene}': found={scene is not None}, has_image={scene.image_url if scene else None}")
            
            if scene and scene.image_url:
                # 从 URL 提取本地路径
                scene_path = scene.image_url.replace("/api/files/", "")
                # 处理已存储的错误格式（可能是反斜杠开头）
                scene_path = scene_path.lstrip("\\/")
                # 统一转换为正斜杠后分割
                scene_path = scene_path.replace("\\", "/")
                # 转换为系统路径格式
                scene_path_parts = scene_path.split("/")
                # 转换为绝对路径
                full_scene_path = os.path.join(os.path.dirname(__file__), "..", "..", "user_story", *scene_path_parts)
                full_scene_path = os.path.abspath(full_scene_path)
                exists = os.path.exists(full_scene_path)
                print(f"[ShotTask {task_id}] Scene '{shot_scene}': path={full_scene_path}, exists={exists}")
                if exists:
                    scene_reference_path = full_scene_path
                    print(f"[ShotTask {task_id}] Found scene image: {shot_scene} -> {full_scene_path}")
        
        # 构建实际提交给ComfyUI的完整工作流（提前构建并保存，让用户可以查看）
        task.current_step = "构建工作流..."
        db.commit()
        
        submitted_workflow = comfyui_service.builder.build_shot_workflow(
            prompt=shot_description,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            style=style
        )
        
        # 如果有角色参考图或场景参考图，先上传图片并更新工作流中的LoadImage节点
        # 这样用户在任务运行期间就能看到实际提交的工作流内容
        if character_reference_path or scene_reference_path:
            task.current_step = "上传参考图..."
            db.commit()
            print(f"[ShotTask {task_id}] Uploading reference images before submission")
            
            # 上传角色参考图（如果存在）
            character_uploaded_filename = None
            if character_reference_path:
                upload_result = await comfyui_service.client.upload_image(character_reference_path)
                if upload_result.get("success"):
                    character_uploaded_filename = upload_result.get("filename")
                    print(f"[ShotTask {task_id}] Character image uploaded successfully: {character_uploaded_filename}")
                else:
                    print(f"[ShotTask {task_id}] Failed to upload character image: {upload_result.get('message')}")
            
            # 上传场景参考图（如果存在）
            scene_uploaded_filename = None
            if scene_reference_path:
                upload_result = await comfyui_service.client.upload_image(scene_reference_path)
                if upload_result.get("success"):
                    scene_uploaded_filename = upload_result.get("filename")
                    print(f"[ShotTask {task_id}] Scene image uploaded successfully: {scene_uploaded_filename}")
                else:
                    print(f"[ShotTask {task_id}] Failed to upload scene image: {upload_result.get('message')}")
            
            # 更新工作流中的LoadImage节点
            if character_uploaded_filename or scene_uploaded_filename:
                # 根据 node_mapping 配置分配图片到指定节点
                character_node_id = node_mapping.get("character_reference_image_node_id")
                scene_node_id = node_mapping.get("scene_reference_image_node_id")
                
                print(f"[ShotTask {task_id}] Node mapping - character_node: {character_node_id}, scene_node: {scene_node_id}")
                
                # 设置角色参考图到指定的 LoadImage 节点
                if character_uploaded_filename and character_node_id:
                    node_id_str = str(character_node_id)
                    if node_id_str in submitted_workflow:
                        submitted_workflow[node_id_str]["inputs"]["image"] = character_uploaded_filename
                        print(f"[ShotTask {task_id}] Set LoadImage node {node_id_str} to character image: {character_uploaded_filename}")
                    else:
                        print(f"[ShotTask {task_id}] Warning: character_reference_image_node_id '{node_id_str}' not found in workflow")
                
                # 设置场景参考图到指定的 LoadImage 节点
                if scene_uploaded_filename and scene_node_id:
                    node_id_str = str(scene_node_id)
                    if node_id_str in submitted_workflow:
                        submitted_workflow[node_id_str]["inputs"]["image"] = scene_uploaded_filename
                        print(f"[ShotTask {task_id}] Set LoadImage node {node_id_str} to scene image: {scene_uploaded_filename}")
                    else:
                        print(f"[ShotTask {task_id}] Warning: scene_reference_image_node_id '{node_id_str}' not found in workflow")
                
                # 保存更新后的工作流（包含替换后的LoadImage节点）到任务
                # 这样即使用户在任务运行期间查看，也能看到实际提交的内容
                task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
                db.commit()
                print(f"[ShotTask {task_id}] Saved workflow with LoadImage replacement to task")
        else:
            # 没有角色参考图，直接保存构建后的工作流
            task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
            db.commit()
            print(f"[ShotTask {task_id}] Saved submitted workflow to task (no character reference)")
        
        # 调用 ComfyUI 生成图片
        task.current_step = "正在调用 ComfyUI 生成图片..."
        task.progress = 30
        db.commit()
        
        # 注意：我们已经上传了图片并更新了工作流，所以不再传递 character_reference_path 或 scene_reference_path
        # 传入的 workflow 已经包含替换后的 LoadImage 节点
        result = await comfyui_service.generate_shot_image_with_workflow(
            prompt=shot_description,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            character_reference_path=None,  # 已经手动处理过了
            scene_reference_path=None,      # 已经手动处理过了
            workflow=submitted_workflow,    # 传递已更新（包含LoadImage替换）的工作流
            style=style
        )
        
        print(f"[ShotTask {task_id}] Generation result: {result}")
        
        # 任务完成后，再次保存最终工作流（以防有后续修改）
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
            print(f"[ShotTask {task_id}] Saved final workflow after task completion")
        
        # 保存 ComfyUI prompt_id 用于取消任务
        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]
            print(f"[ShotTask {task_id}] Saved ComfyUI prompt_id: {result['prompt_id']}")
        
        if not result.get("success"):
            task.status = "failed"
            task.error_message = result.get("message", "生成失败")
            task.current_step = "生成失败"
            db.commit()
            return
        
        # 下载生成的图片
        task.current_step = "正在下载生成的图片..."
        task.progress = 80
        db.commit()
        
        image_url = result.get("image_url")
        if image_url:
            local_path = await file_storage.download_image(
                url=image_url,
                novel_id=novel_id,
                character_name=f"shot_{shot_index:03d}",
                image_type="shot",
                chapter_id=chapter_id
            )
            
            if local_path:
                # 构建本地可访问的URL
                relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                local_url = f"/api/files/{relative_path.lstrip('/')}"
                
                # 更新任务状态
                task.status = "completed"
                task.progress = 100
                task.result_url = local_url
                task.current_step = "生成完成"
                task.completed_at = datetime.utcnow()
                db.commit()
                
                # 重新获取最新的章节数据，避免并发覆盖
                db.refresh(chapter)
                latest_parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {"shots": []}
                
                # 确保 shots 数组存在且长度足够
                if "shots" not in latest_parsed_data:
                    latest_parsed_data["shots"] = []
                while len(latest_parsed_data["shots"]) < shot_index:
                    latest_parsed_data["shots"].append({})
                
                # 更新分镜数据
                latest_parsed_data["shots"][shot_index - 1]["image_path"] = str(local_path)
                latest_parsed_data["shots"][shot_index - 1]["image_url"] = local_url
                
                # 保存回数据库
                chapter.parsed_data = json.dumps(latest_parsed_data, ensure_ascii=False)
                
                # 同时更新 shot_images 数组（前端优先从这个数组读取）
                shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
                if not isinstance(shot_images, list):
                    shot_images = []
                while len(shot_images) < shot_index:
                    shot_images.append(None)
                shot_images[shot_index - 1] = local_url
                chapter.shot_images = json.dumps(shot_images, ensure_ascii=False)
                
                db.commit()
                
                print(f"[ShotTask {task_id}] Completed, image saved: {local_path}")
            else:
                # 下载失败，使用远程URL，但也要保存到 parsed_data
                task.status = "completed"
                task.progress = 100
                task.result_url = image_url
                task.current_step = "生成完成（使用远程图片）"
                task.completed_at = datetime.utcnow()
                db.commit()
                
                # 同样更新 parsed_data
                db.refresh(chapter)
                latest_parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {"shots": []}
                if "shots" not in latest_parsed_data:
                    latest_parsed_data["shots"] = []
                while len(latest_parsed_data["shots"]) < shot_index:
                    latest_parsed_data["shots"].append({})
                latest_parsed_data["shots"][shot_index - 1]["image_url"] = image_url
                chapter.parsed_data = json.dumps(latest_parsed_data, ensure_ascii=False)
                
                # 同时更新 shot_images 数组
                shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
                if not isinstance(shot_images, list):
                    shot_images = []
                while len(shot_images) < shot_index:
                    shot_images.append(None)
                shot_images[shot_index - 1] = image_url
                chapter.shot_images = json.dumps(shot_images, ensure_ascii=False)
                
                db.commit()
        else:
            task.status = "failed"
            task.error_message = "未获取到图片URL"
            task.current_step = "生成失败"
            db.commit()
            
    except Exception as e:
        print(f"[ShotTask {task_id}] Error: {e}")
        import traceback
        traceback.print_exc()
        
        try:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"
            db.commit()
        except:
            pass
    finally:
        db.close()


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/generate-video", response_model=dict)
async def generate_shot_video(
    novel_id: str,
    chapter_id: str,
    shot_index: int,  # 1-based index
    db: Session = Depends(get_db)
):
    """
    为指定分镜生成视频（基于已生成的分镜图片）
    """
    from app.models.workflow import Workflow
    
    # 获取章节
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 获取小说
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 解析章节数据
    if not chapter.parsed_data:
        raise HTTPException(status_code=400, detail="章节未拆分，请先进行AI拆分")
    
    parsed_data = json.loads(chapter.parsed_data) if isinstance(chapter.parsed_data, str) else chapter.parsed_data
    shots = parsed_data.get("shots", [])
    
    if shot_index < 1 or shot_index > len(shots):
        raise HTTPException(status_code=400, detail="分镜索引超出范围")
    
    shot = shots[shot_index - 1]
    shot_duration = shot.get("duration", 4)  # 获取分镜时长，默认4秒
    
    # 检查是否有已生成的分镜图片
    shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
    shot_image_url = None
    
    # 从 shot_images 数组中获取对应索引的图片
    if isinstance(shot_images, list) and len(shot_images) >= shot_index:
        shot_image_url = shot_images[shot_index - 1]
    
    # 也检查 parsed_data 中的 image_url
    if not shot_image_url:
        shot_image_url = shot.get("image_url")
    
    if not shot_image_url:
        raise HTTPException(status_code=400, detail="该分镜尚未生成图片，请先生成分镜图片")
    
    # 检查是否已有进行中的视频生成任务
    existing_task = db.query(Task).filter(
        Task.novel_id == novel_id,
        Task.chapter_id == chapter_id,
        Task.type == "shot_video",
        Task.name.like(f"%镜{shot_index}%"),
        Task.status.in_(["pending", "running"])
    ).first()
    
    if existing_task:
        return {
            "success": True,
            "message": "已有进行中的视频生成任务",
            "data": {
                "taskId": existing_task.id,
                "status": existing_task.status
            }
        }
    
    # 检查是否有失败的任务，如果有则删除旧任务以便重新生成
    failed_task = db.query(Task).filter(
        Task.novel_id == novel_id,
        Task.chapter_id == chapter_id,
        Task.type == "shot_video",
        Task.name.like(f"%镜{shot_index}%"),
        Task.status == "failed"
    ).first()
    
    if failed_task:
        print(f"[GenerateVideo] Deleting failed task {failed_task.id} for shot {shot_index} to allow regeneration")
        db.delete(failed_task)
        db.commit()
    
    # 【关键】清除该分镜的旧视频记录（避免前端显示旧视频）
    shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
    if isinstance(shot_videos, list) and len(shot_videos) >= shot_index:
        old_video_url = shot_videos[shot_index - 1]
        if old_video_url:
            print(f"[GenerateVideo] Clearing old video record for shot {shot_index}: {old_video_url}")
            shot_videos[shot_index - 1] = None
            chapter.shot_videos = json.dumps(shot_videos)
            db.commit()
    
    # 获取激活的视频生成工作流
    workflow = db.query(Workflow).filter(
        Workflow.type == "video",
        Workflow.is_active == True
    ).first()
    
    if not workflow:
        raise HTTPException(status_code=400, detail="未配置视频生成工作流，请在系统设置中配置")
    
    # 验证工作流节点映射配置
    is_valid, error_msg = validate_workflow_node_mapping(workflow, "video")
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    # 创建任务记录
    task = Task(
        type="shot_video",
        name=f"生成视频: 镜{shot_index}",
        description=f"为章节 '{chapter.title}' 的分镜 {shot_index} 生成视频 (时长: {shot_duration}s)",
        novel_id=novel_id,
        chapter_id=chapter_id,
        status="pending",
        workflow_id=workflow.id,
        workflow_name=workflow.name
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    
    print(f"[GenerateVideo] Created task {task.id} for shot {shot_index}")
    
    # 启动后台任务
    asyncio.create_task(
        generate_shot_video_task(
            task.id,
            novel_id,
            chapter_id,
            shot_index,
            workflow.id,
            shot_image_url
        )
    )
    
    return {
        "success": True,
        "message": "视频生成任务已创建",
        "data": {
            "taskId": task.id,
            "status": "pending"
        }
    }


async def generate_shot_video_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    workflow_id: str,
    shot_image_url: str
):
    """
    后台任务：生成分镜视频
    """
    import os
    from app.models.workflow import Workflow
    from app.services.file_storage import file_storage
    from app.core.database import SessionLocal
    
    db = SessionLocal()
    try:
        # 获取任务
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        
        # 更新任务状态为运行中
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.current_step = "准备生成视频..."
        db.commit()
        
        # 获取章节和小说
        chapter = db.query(Chapter).filter(
            Chapter.id == chapter_id,
            Chapter.novel_id == novel_id
        ).first()
        
        if not chapter:
            task.status = "failed"
            task.error_message = "章节不存在"
            db.commit()
            return
        
        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        if not novel:
            task.status = "failed"
            task.error_message = "小说不存在"
            db.commit()
            return
        
        # 获取工作流
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            task.status = "failed"
            task.error_message = "工作流不存在"
            db.commit()
            return
        
        # 获取节点映射
        node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}
        print(f"[VideoTask {task_id}] Node mapping: {node_mapping}")
        
        # 解析章节数据获取分镜描述
        parsed_data = json.loads(chapter.parsed_data) if isinstance(chapter.parsed_data, str) else chapter.parsed_data
        shots = parsed_data.get("shots", [])
        shot = shots[shot_index - 1]
        # 使用 video_description 作为视频生成的提示词，如果不存在则回退到 description
        shot_description = shot.get("video_description") or shot.get("description", "")
        
        # 保存提示词到任务
        task.prompt_text = shot_description
        db.commit()
        
        # 获取分镜时长并计算总帧数
        duration = shot.get("duration", 4)  # 默认4秒
        fps = 25  # LTX 默认帧率
        raw_frame_count = int(fps * duration)
        # 计算最接近的 8 的倍数 + 1
        frame_count = ((raw_frame_count // 8) * 8) + 1
        print(f"[VideoTask {task_id}] Duration: {duration}s, FPS: {fps}, Raw frames: {raw_frame_count}, Adjusted frames: {frame_count}")
        
        # 获取分镜图片的本地路径
        character_reference_path = None
        if shot_image_url:
            # 从 URL 提取本地路径
            char_path = shot_image_url.replace("/api/files/", "")
            # 处理已存储的错误格式（可能是反斜杠开头）
            char_path = char_path.lstrip("\\/")
            # 统一转换为正斜杠后分割
            char_path = char_path.replace("\\", "/")
            # 转换为系统路径格式
            char_path_parts = char_path.split("/")
            full_path = os.path.join(os.path.dirname(__file__), "..", "..", "user_story", *char_path_parts)
            full_path = os.path.abspath(full_path)
            if os.path.exists(full_path):
                character_reference_path = full_path
                print(f"[VideoTask {task_id}] Found shot image: {full_path}")
            else:
                print(f"[VideoTask {task_id}] Shot image not found at: {full_path}")
        
        # 调用 ComfyUI 生成视频
        task.current_step = "正在调用 ComfyUI 生成视频..."
        task.progress = 30
        db.commit()
        
        result = await comfyui_service.generate_shot_video_with_workflow(
            prompt=shot_description,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            character_reference_path=character_reference_path,
            frame_count=frame_count
        )
        
        print(f"[VideoTask {task_id}] Generation result: {result}")
        
        # 保存 ComfyUI prompt_id 用于取消任务
        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]
            print(f"[VideoTask {task_id}] Saved ComfyUI prompt_id: {result['prompt_id']}")
        
        # 保存实际提交给ComfyUI的工作流（包含所有替换后的参数）
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
            print(f"[VideoTask {task_id}] Saved submitted workflow to task")
        
        if not result.get("success"):
            task.status = "failed"
            task.error_message = result.get("message", "生成失败")
            task.current_step = "生成失败"
            db.commit()
            return
        
        # 下载生成的视频
        task.current_step = "正在下载生成的视频..."
        task.progress = 80
        db.commit()
        
        video_url = result.get("video_url")
        if video_url:
            local_path = await file_storage.download_video(
                url=video_url,
                novel_id=novel_id,
                chapter_id=chapter_id,
                shot_number=shot_index
            )
            
            if local_path:
                # 构建本地可访问的URL
                relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                local_url = f"/api/files/{relative_path.lstrip('/')}"
                
                # 更新章节的视频列表
                shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
                if not isinstance(shot_videos, list):
                    shot_videos = []
                
                # 确保数组足够长
                while len(shot_videos) < shot_index:
                    shot_videos.append(None)
                
                shot_videos[shot_index - 1] = local_url
                chapter.shot_videos = json.dumps(shot_videos)
                
                # 更新任务状态
                task.status = "completed"
                task.progress = 100
                task.result_url = local_url
                task.current_step = "生成完成"
                task.completed_at = datetime.utcnow()
                db.commit()
                
                print(f"[VideoTask {task_id}] Video saved: {local_url}")
            else:
                task.status = "failed"
                task.error_message = "下载视频失败"
                task.current_step = "下载失败"
                db.commit()
        else:
            task.status = "failed"
            task.error_message = "未获取到视频URL"
            task.current_step = "生成失败"
            db.commit()
            
    except Exception as e:
        print(f"[VideoTask {task_id}] Error: {e}")
        import traceback
        traceback.print_exc()
        
        try:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"
            db.commit()
        except:
            pass
    finally:
        db.close()


# ==================== 转场视频生成 API ====================

@router.post("/{novel_id}/chapters/{chapter_id}/transitions", response_model=dict)
async def generate_transition_video(
    novel_id: str,
    chapter_id: str,
    data: dict,
    db: Session = Depends(get_db)
):
    """
    生成转场视频（两个分镜之间）
    
    Request Body:
    {
        "from_index": 1,       // 起始分镜索引 (1-based)
        "to_index": 2,         // 结束分镜索引 (1-based)
        "frame_count": 49,     // 可选，总帧数（8的倍数+1）
        "workflow_id": "xxx"   // 可选，指定工作流ID（不指定则使用默认）
    }
    """
    # 获取章节
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    from_index = data.get("from_index")
    to_index = data.get("to_index")
    frame_count = data.get("frame_count", 49)  # 默认49帧 (约2秒@25fps)
    workflow_id = data.get("workflow_id")  # 可选，自定义工作流ID
    
    if not from_index or not to_index:
        raise HTTPException(status_code=400, detail="缺少 from_index 或 to_index")
    
    # 解析分镜数据
    parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {}
    shots = parsed_data.get("shots", [])
    
    if from_index < 1 or to_index > len(shots) or from_index >= to_index:
        raise HTTPException(status_code=400, detail="无效的分镜索引")
    
    # 获取分镜视频（转场需要视频而不是图片）
    shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
    
    first_video = shot_videos[from_index - 1] if from_index <= len(shot_videos) else None
    second_video = shot_videos[to_index - 1] if to_index <= len(shot_videos) else None
    
    if not first_video or not second_video:
        raise HTTPException(status_code=400, detail="分镜视频尚未生成，请先生成分镜视频")
    
    # 检查是否已有进行中的转场视频任务
    transition_key = f"{from_index}-{to_index}"
    existing_task = db.query(Task).filter(
        Task.novel_id == novel_id,
        Task.chapter_id == chapter_id,
        Task.type == "transition_video",
        Task.name.like(f"%镜{from_index}-镜{to_index}%"),
        Task.status.in_(["pending", "running"])
    ).first()
    
    if existing_task:
        return {
            "success": True,
            "message": "转场视频生成任务已在进行中",
            "task_id": existing_task.id,
            "status": existing_task.status
        }
    
    # 获取转场视频工作流
    from app.models.workflow import Workflow
    if workflow_id:
        # 使用指定的工作流
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise HTTPException(status_code=400, detail="指定的工作流不存在")
    else:
        # 使用默认的激活工作流
        workflow = db.query(Workflow).filter(
            Workflow.type == "transition",
            Workflow.is_active == True
        ).first()
    
    if not workflow:
        raise HTTPException(status_code=400, detail="未配置转场视频工作流，请在系统设置中配置")
    
    # 验证工作流节点映射配置
    is_valid, error_msg = validate_workflow_node_mapping(workflow, "transition")
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    # 创建任务记录
    task = Task(
        type="transition_video",
        name=f"生成转场视频: 镜{from_index}→镜{to_index}",
        description=f"为章节 '{chapter.title}' 的分镜 {from_index} 到 {to_index} 生成转场过渡视频",
        novel_id=novel_id,
        chapter_id=chapter_id,
        status="pending",
        progress=0,
        current_step="等待处理",
        workflow_id=workflow.id,
        workflow_name=workflow.name
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    
    print(f"[Transition] Created task {task.id} for transition {from_index}->{to_index} using workflow {workflow.name}")
    
    # 启动后台任务
    asyncio.create_task(
        generate_transition_video_task(
            task.id,
            novel_id,
            chapter_id,
            from_index,
            to_index,
            workflow.id,
            frame_count
        )
    )
    
    return {
        "success": True,
        "message": "转场视频生成任务已创建",
        "task_id": task.id,
        "status": "pending"
    }


@router.post("/{novel_id}/chapters/{chapter_id}/transitions/batch", response_model=dict)
async def generate_all_transitions(
    novel_id: str,
    chapter_id: str,
    data: dict = {},
    db: Session = Depends(get_db)
):
    """
    一键生成所有相邻分镜之间的转场视频
    
    Request Body:
    {
        "frame_count": 49,     // 可选，总帧数
        "workflow_id": "xxx"   // 可选，指定工作流ID（不指定则使用默认）
    }
    """
    # 获取章节
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 解析分镜数据
    parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {}
    shots = parsed_data.get("shots", [])
    
    if len(shots) < 2:
        raise HTTPException(status_code=400, detail="分镜数量不足，无法生成转场")
    
    # 获取分镜视频（转场需要视频）
    shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
    
    # 检查是否所有分镜都有视频
    if len(shot_videos) < len(shots):
        raise HTTPException(status_code=400, detail="部分分镜视频尚未生成，请先生成所有分镜视频")
    
    frame_count = data.get("frame_count", 49)
    workflow_id = data.get("workflow_id")  # 可选，自定义工作流ID
    
    # 获取转场视频工作流
    from app.models.workflow import Workflow
    if workflow_id:
        # 使用指定的工作流
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise HTTPException(status_code=400, detail="指定的工作流不存在")
    else:
        # 使用默认的激活工作流
        workflow = db.query(Workflow).filter(
            Workflow.type == "transition",
            Workflow.is_active == True
        ).first()
    
    if not workflow:
        raise HTTPException(status_code=400, detail="未配置转场视频工作流")
    
    # 为每对相邻分镜创建任务
    task_ids = []
    for i in range(1, len(shots)):
        from_idx = i
        to_idx = i + 1
        
        # 检查是否已有进行中的任务
        existing_task = db.query(Task).filter(
            Task.novel_id == novel_id,
            Task.chapter_id == chapter_id,
            Task.type == "transition_video",
            Task.name.like(f"%镜{from_idx}-镜{to_idx}%"),
            Task.status.in_(["pending", "running"])
        ).first()
        
        if existing_task:
            task_ids.append(existing_task.id)
            continue
        
        task = Task(
            type="transition_video",
            name=f"生成转场视频: 镜{from_idx}→镜{to_idx}",
            description=f"为章节 '{chapter.title}' 的分镜 {from_idx} 到 {to_idx} 生成转场过渡视频",
            novel_id=novel_id,
            chapter_id=chapter_id,
            status="pending",
            progress=0,
            current_step="等待处理",
            workflow_id=workflow.id,
            workflow_name=workflow.name
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_ids.append(task.id)
        
        # 延迟启动，避免同时提交过多任务
        asyncio.create_task(
            generate_transition_video_task(
                task.id,
                novel_id,
                chapter_id,
                from_idx,
                to_idx,
                workflow.id,
                frame_count
            )
        )
    
    return {
        "success": True,
        "message": f"已创建 {len(task_ids)} 个转场视频生成任务",
        "task_count": len(task_ids),
        "task_ids": task_ids
    }


async def generate_transition_video_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    from_index: int,
    to_index: int,
    workflow_id: str,
    frame_count: int = 49
):
    """后台任务：生成转场视频（从视频提取首帧/尾帧）"""
    from app.core.database import SessionLocal
    from app.services.file_storage import file_storage
    from pathlib import Path
    import os
    
    db = SessionLocal()
    
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            print(f"[TransitionTask] Task {task_id} not found")
            return
        
        task.status = "running"
        task.current_step = "准备生成转场视频..."
        task.progress = 10
        db.commit()
        
        # 获取章节和视频
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
        if not chapter:
            raise Exception("章节不存在")
        
        shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
        
        # 获取前后两个视频的 URL
        first_video_url = shot_videos[from_index - 1] if from_index <= len(shot_videos) else None
        second_video_url = shot_videos[to_index - 1] if to_index <= len(shot_videos) else None
        
        if not first_video_url or not second_video_url:
            raise Exception("分镜视频尚未生成")
        
        # 转换URL为本地路径
        first_video_path = None
        second_video_path = None
        
        if first_video_url.startswith("/api/files/"):
            relative_path = first_video_url.replace("/api/files/", "")
            # 处理已存储的错误格式（可能是反斜杠开头）
            relative_path = relative_path.lstrip("\\/")
            # 统一转换为正斜杠后分割
            relative_path = relative_path.replace("\\", "/")
            # 转换为系统路径格式
            path_parts = relative_path.split("/")
            first_video_path = os.path.join(str(file_storage.base_dir), *path_parts)
        
        if second_video_url.startswith("/api/files/"):
            relative_path = second_video_url.replace("/api/files/", "")
            # 处理已存储的错误格式（可能是反斜杠开头）
            relative_path = relative_path.lstrip("\\/")
            # 统一转换为正斜杠后分割
            relative_path = relative_path.replace("\\", "/")
            # 转换为系统路径格式
            path_parts = relative_path.split("/")
            second_video_path = os.path.join(str(file_storage.base_dir), *path_parts)
        
        if not first_video_path or not second_video_path:
            raise Exception("无法解析视频路径")
        
        if not os.path.exists(first_video_path) or not os.path.exists(second_video_path):
            raise Exception("视频文件不存在")
        
        # 获取视频文件名（不含扩展名）用于生成转场视频文件名
        first_video_name = Path(first_video_path).stem
        second_video_name = Path(second_video_path).stem
        
        task.current_step = "正在提取视频帧..."
        task.progress = 20
        db.commit()
        
        # 提取前一个视频的尾帧
        first_frames = await file_storage.extract_video_frames(first_video_path)
        if not first_frames.get("success") or not first_frames.get("last"):
            raise Exception(f"无法提取第一个视频的尾帧: {first_frames.get('message')}")
        
        # 提取后一个视频的首帧
        second_frames = await file_storage.extract_video_frames(second_video_path)
        if not second_frames.get("success") or not second_frames.get("first"):
            raise Exception(f"无法提取第二个视频的首帧: {second_frames.get('message')}")
        
        # 转场视频输入：前一个视频的尾帧 + 后一个视频的首帧
        last_frame_path = first_frames["last"]
        first_frame_path = second_frames["first"]
        
        task.current_step = "正在调用 ComfyUI 生成转场视频..."
        task.progress = 40
        db.commit()
        
        # 获取工作流
        from app.models.workflow import Workflow
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise Exception("工作流不存在")
        
        # 解析节点映射
        node_mapping = {}
        if workflow.node_mapping:
            try:
                node_mapping = json.loads(workflow.node_mapping)
            except:
                pass
        
        # 生成转场视频
        # 注意：转场是从分镜A过渡到分镜B
        # - First IMG（首帧输入）应该是分镜A的尾帧
        # - End IMG（尾帧输入）应该是分镜B的首帧
        result = await comfyui_service.generate_transition_video_with_workflow(
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            first_image_path=last_frame_path,   # 前一个视频的尾帧作为 First IMG
            last_image_path=first_frame_path,   # 后一个视频的首帧作为 End IMG
            frame_count=frame_count
        )
        
        # 保存 ComfyUI prompt_id 用于取消任务
        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]
            print(f"[TransitionTask] Saved ComfyUI prompt_id: {result['prompt_id']}")
        
        # 保存实际提交给ComfyUI的工作流
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
            print(f"[TransitionTask] Saved submitted workflow to task")
        
        if result.get("success"):
            video_url = result.get("video_url")
            
            # 保存到 transition-videos 目录
            task.current_step = "正在保存视频..."
            task.progress = 80
            db.commit()
            
            # 构建保存路径
            transition_path = file_storage.get_transition_video_path(
                novel_id, chapter_id, first_video_name, second_video_name
            )
            
            # 下载视频
            async with httpx.AsyncClient() as client:
                response = await client.get(video_url, timeout=120.0)
                response.raise_for_status()
                
                with open(transition_path, 'wb') as f:
                    f.write(response.content)
            
            # 构建本地访问 URL
            relative_path = str(transition_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
            local_url = f"/api/files/{relative_path.lstrip('/')}"
            
            # 更新章节的转场视频记录
            transition_videos = json.loads(chapter.transition_videos) if chapter.transition_videos else {}
            if not isinstance(transition_videos, dict):
                transition_videos = {}
            
            transition_key = f"{from_index}-{to_index}"
            transition_videos[transition_key] = local_url
            chapter.transition_videos = json.dumps(transition_videos)
            
            # 更新任务状态
            task.status = "completed"
            task.progress = 100
            task.result_url = local_url
            task.current_step = "转场视频生成完成"
            db.commit()
            
            print(f"[TransitionTask] Completed: {from_index}->{to_index}, video: {local_url}")
        else:
            raise Exception(result.get("message", "生成失败"))
            
    except Exception as e:
        print(f"[TransitionTask] Error: {e}")
        import traceback
        traceback.print_exc()
        
        try:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"
            db.commit()
        except:
            pass
    finally:
        db.close()


@router.get("/{novel_id}/chapters/{chapter_id}/download-materials", response_model=dict)
async def download_chapter_materials(
    novel_id: str,
    chapter_id: str,
    db: Session = Depends(get_db)
):
    """
    下载章节素材 ZIP 包
    
    打包内容包括：
    - merged_characters/ 合并角色图
    - shots/ 分镜图片
    - transition-videos/ 转场视频
    - videos/ 分镜视频
    """
    # 验证小说和章节存在
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 生成 ZIP 文件
    zip_path = file_storage.zip_chapter_materials(novel_id, chapter_id)
    
    if not zip_path:
        raise HTTPException(status_code=404, detail="章节素材不存在或打包失败")
    
    # 返回文件
    chapter_short = chapter_id[:8] if chapter_id else "unknown"
    filename = f"{novel.title}_chapter_{chapter_short}_materials.zip"
    
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename
    )


@router.post("/{novel_id}/chapters/{chapter_id}/merge-videos", response_model=dict)
async def merge_chapter_videos(
    novel_id: str,
    chapter_id: str,
    data: dict,
    db: Session = Depends(get_db)
):
    """
    合并章节视频
    
    Args:
        data: {
            "include_transitions": bool  # 是否包含转场视频
        }
    
    Returns:
        {
            "success": bool,
            "video_url": str,
            "message": str
        }
    """
    # 验证小说和章节存在
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    include_transitions = data.get("include_transitions", False)
    
    # 获取视频列表
    shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
    transition_videos = json.loads(chapter.transition_videos) if chapter.transition_videos else {}
    
    if not shot_videos or len(shot_videos) == 0:
        return {
            "success": False,
            "message": "没有分镜视频可以合并"
        }
    
    # 转换 URL 为本地路径
    video_paths = []
    for video_url in shot_videos:
        if video_url.startswith("/api/files/"):
            relative_path = video_url.replace("/api/files/", "")
            # 处理已存储的错误格式（可能是反斜杠开头）
            relative_path = relative_path.lstrip("\\/")
            # 统一转换为正斜杠后分割
            relative_path = relative_path.replace("\\", "/")
            # 转换为系统路径格式
            path_parts = relative_path.split("/")
            full_path = os.path.join(str(file_storage.base_dir), *path_parts)
            if os.path.exists(full_path):
                video_paths.append(full_path)
    
    if len(video_paths) == 0:
        return {
            "success": False,
            "message": "视频文件不存在"
        }
    
    # 获取转场视频路径
    trans_paths = []
    if include_transitions and transition_videos:
        for i in range(len(shot_videos) - 1):
            key = f"{i+1}-{i+2}"
            trans_url = transition_videos.get(key)
            if trans_url and trans_url.startswith("/api/files/"):
                relative_path = trans_url.replace("/api/files/", "")
                # 处理已存储的错误格式（可能是反斜杠开头）
                relative_path = relative_path.lstrip("\\/")
                # 统一转换为正斜杠后分割
                relative_path = relative_path.replace("\\", "/")
                # 转换为系统路径格式
                path_parts = relative_path.split("/")
                full_path = os.path.join(str(file_storage.base_dir), *path_parts)
                if os.path.exists(full_path):
                    trans_paths.append(full_path)
                else:
                    trans_paths.append(None)
            else:
                trans_paths.append(None)
    
    # 生成输出路径
    story_dir = file_storage._get_story_dir(novel_id)
    chapter_short = chapter_id[:8] if chapter_id else "unknown"
    output_filename = f"chapter_{chapter_short}_merged{'_with_trans' if include_transitions else ''}.mp4"
    output_path = str(story_dir / output_filename)
    
    # 合并视频
    result = await file_storage.merge_videos(
        video_paths, 
        output_path, 
        trans_paths if include_transitions else None
    )
    
    if result.get("success"):
        # 构建访问 URL
        relative_path = output_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
        video_url = f"/api/files/{relative_path.lstrip('/')}"
        
        return {
            "success": True,
            "video_url": video_url,
            "message": result.get("message", "合并成功")
        }
    else:
        return {
            "success": False,
            "message": result.get("message", "合并失败")
        }


@router.post("/{novel_id}/chapters/{chapter_id}/clear-resources", response_model=dict)
async def clear_chapter_resources(
    novel_id: str,
    chapter_id: str,
    db: Session = Depends(get_db)
):
    """
    清除章节的所有生成资源（用于重新拆分分镜头前）
    
    清除的内容：
    - parsed_data (分镜头 JSON 数据)
    - shot_images (分镜头图片数组)
    - shot_videos (分镜头视频数组)
    - transition_videos (转场视频字典)
    - merged_image (合并角色图)
    - 物理文件（整个章节目录）
    """
    # 验证小说和章节存在
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 【第一步】删除物理文件（整个章节目录）
    print(f"[ClearResources] Deleting physical files for chapter {chapter_id}")
    file_deleted = file_storage.delete_chapter_directory(novel_id, chapter_id)
    
    # 【第二步】清除数据库记录
    chapter.parsed_data = None
    chapter.shot_images = None
    chapter.shot_videos = None
    chapter.transition_videos = None
    chapter.merged_image = None
    
    db.commit()
    
    print(f"[ClearResources] Chapter resources cleared. Files deleted: {file_deleted}")
    
    return {
        "success": True,
        "message": "章节资源已清除" + ("（包含物理文件）" if file_deleted else "（物理文件清除失败）"),
        "files_deleted": file_deleted
    }
