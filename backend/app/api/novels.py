"""
小说路由 - 小说 CRUD 和解析相关接口
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Novel
from app.schemas.novel import NovelCreate
from app.repositories import NovelRepository, ChapterRepository, CharacterRepository, PromptTemplateRepository
from app.services.novel_service import NovelService
from app.api.deps import get_novel_repo, get_chapter_repo, get_character_repo
from app.utils.time_utils import format_datetime

router = APIRouter()


# ==================== 小说 CRUD ====================

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
    from app.repositories import PromptTemplateRepository
    
    prompt_template_repo = PromptTemplateRepository(db)
    
    # 如果没有指定角色生成模板，使用默认系统模板
    prompt_template_id = novel.prompt_template_id
    if not prompt_template_id:
        default_template = prompt_template_repo.get_default_system_template("character")
        if default_template:
            prompt_template_id = default_template.id
    
    # 如果没有指定风格模板，使用默认系统模板
    style_prompt_template_id = novel.style_prompt_template_id
    if not style_prompt_template_id:
        default_style = prompt_template_repo.get_default_system_template("style")
        if default_style:
            style_prompt_template_id = default_style.id
    
    db_novel = Novel(
        title=novel.title,
        author=novel.author,
        description=novel.description,
        style_prompt_template_id=style_prompt_template_id,
        character_parse_prompt_template_id=novel.character_parse_prompt_template_id,
        scene_parse_prompt_template_id=novel.scene_parse_prompt_template_id,
        prop_parse_prompt_template_id=novel.prop_parse_prompt_template_id,
        prompt_template_id=prompt_template_id,
        scene_prompt_template_id=novel.scene_prompt_template_id,
        prop_prompt_template_id=novel.prop_prompt_template_id,
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
            "stylePromptTemplateId": db_novel.style_prompt_template_id,
            "characterParsePromptTemplateId": db_novel.character_parse_prompt_template_id,
            "sceneParsePromptTemplateId": db_novel.scene_parse_prompt_template_id,
            "propParsePromptTemplateId": db_novel.prop_parse_prompt_template_id,
            "promptTemplateId": db_novel.prompt_template_id,
            "scenePromptTemplateId": db_novel.scene_prompt_template_id,
            "propPromptTemplateId": db_novel.prop_prompt_template_id,
            "chapterSplitPromptTemplateId": db_novel.chapter_split_prompt_template_id,
            "aspectRatio": db_novel.aspect_ratio or "16:9",
            "createdAt": format_datetime(db_novel.created_at),
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
        "data": novel_repo.to_response(novel)
    }


@router.put("/{novel_id}", response_model=dict)
async def update_novel(
    novel_id: str, 
    data: dict, 
    db: Session = Depends(get_db), 
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """更新小说信息"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 更新字段
    update_fields = {
        "title": "title",
        "author": "author", 
        "description": "description",
        "stylePromptTemplateId": "style_prompt_template_id",
        "characterParsePromptTemplateId": "character_parse_prompt_template_id",
        "sceneParsePromptTemplateId": "scene_parse_prompt_template_id",
        "propParsePromptTemplateId": "prop_parse_prompt_template_id",
        "promptTemplateId": "prompt_template_id",
        "scenePromptTemplateId": "scene_prompt_template_id",
        "propPromptTemplateId": "prop_prompt_template_id",
        "chapterSplitPromptTemplateId": "chapter_split_prompt_template_id",
        "aspectRatio": "aspect_ratio",
    }
    
    for api_field, db_field in update_fields.items():
        if api_field in data:
            setattr(novel, db_field, data[api_field])
    
    db.commit()
    db.refresh(novel)
    
    return {
        "success": True,
        "data": {
            **novel_repo.to_response(novel),
            "updatedAt": format_datetime(novel.updated_at),
        }
    }


@router.delete("/{novel_id}")
async def delete_novel(
    novel_id: str, 
    db: Session = Depends(get_db), 
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """删除小说"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    db.delete(novel)
    db.commit()
    
    return {"success": True, "message": "删除成功"}


# ==================== 小说解析 ====================

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
    from app.services.novel_service import NovelService
    
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 获取指定章节范围的章节
    chapters = chapter_repo.get_by_range(novel_id, start_chapter, end_chapter)
    
    if not chapters:
        return {"success": False, "message": "指定章节范围内没有内容"}
    
    service = NovelService(db)
    return await service.parse_characters(
        novel_id=novel_id,
        chapters=chapters,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        is_incremental=is_incremental,
        character_repo=character_repo
    )


@router.post("/{novel_id}/parse-props/", response_model=dict)
async def parse_props(
    novel_id: str,
    sync: bool = False,
    start_chapter: int = None,
    end_chapter: int = None,
    is_incremental: bool = False,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo)
):
    """解析小说内容，自动提取道具信息（支持章节范围和增量更新）"""
    from app.services.novel_service import NovelService
    from app.repositories import PropRepository

    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 获取指定章节范围的章节
    chapters = chapter_repo.get_by_range(novel_id, start_chapter, end_chapter)

    if not chapters:
        return {"success": False, "message": "指定章节范围内没有内容"}

    prop_repo = PropRepository(db)
    service = NovelService(db)
    return await service.parse_props(
        novel_id=novel_id,
        chapters=chapters,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        is_incremental=is_incremental,
        prop_repo=prop_repo
    )
