"""
小说路由 - 小说 CRUD 和解析相关接口
"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.schemas.novel import NovelCreate
from app.services.llm_service import LLMService
from app.repositories import NovelRepository, ChapterRepository, CharacterRepository
from app.utils.time_utils import format_datetime

router = APIRouter()


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
    
    # 如果没有指定提示词模板，使用默认系统模板
    prompt_template_id = novel.prompt_template_id
    if not prompt_template_id:
        default_template = prompt_template_repo.get_first_system_template()
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
        "promptTemplateId": "prompt_template_id",
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

@router.post("/{novel_id}/parse", response_model=dict)
async def parse_novel(
    novel_id: str, 
    db: Session = Depends(get_db), 
    novel_repo: NovelRepository = Depends(get_novel_repo), 
    chapter_repo: ChapterRepository = Depends(get_chapter_repo)
):
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
