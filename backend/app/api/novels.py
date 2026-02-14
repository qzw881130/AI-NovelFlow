import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.novel import Novel, Chapter, Character
from app.models.prompt_template import PromptTemplate
from app.schemas.novel import NovelCreate, NovelResponse, ChapterCreate, ChapterResponse
from app.services.deepseek import DeepSeekService
from app.services.comfyui import ComfyUIService

deepseek_service = DeepSeekService()
comfyui_service = ComfyUIService()

router = APIRouter()


@router.get("/", response_model=dict)
async def list_novels(db: Session = Depends(get_db)):
    """获取小说列表"""
    novels = db.query(Novel).order_by(Novel.created_at.desc()).all()
    return {
        "success": True,
        "data": [
            {
                "id": n.id,
                "title": n.title,
                "author": n.author,
                "description": n.description,
                "cover": n.cover,
                "status": n.status,
                "chapterCount": n.chapter_count,
                "promptTemplateId": n.prompt_template_id,
                "chapterSplitPromptTemplateId": n.chapter_split_prompt_template_id,
                "aspectRatio": n.aspect_ratio if n.aspect_ratio and n.aspect_ratio.strip() else "16:9",
                "createdAt": n.created_at.isoformat() if n.created_at else None,
                "updatedAt": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in novels
        ]
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
async def get_novel(novel_id: str, db: Session = Depends(get_db)):
    """获取小说详情"""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
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
async def update_novel(novel_id: str, data: dict, db: Session = Depends(get_db)):
    """更新小说信息"""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
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
async def delete_novel(novel_id: str, db: Session = Depends(get_db)):
    """删除小说"""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    db.delete(novel)
    db.commit()
    
    return {"success": True, "message": "删除成功"}


@router.post("/{novel_id}/parse", response_model=dict)
async def parse_novel(novel_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """解析小说内容，提取角色和场景"""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 获取所有章节内容
    chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id).all()
    full_text = "\n\n".join([c.content for c in chapters if c.content])
    
    # 更新状态为解析中
    novel.status = "processing"
    db.commit()
    
    # 异步解析
    async def do_parse():
        try:
            result = await deepseek_service.parse_novel_text(full_text)
            
            # 保存解析结果到各个章节
            for chapter in chapters:
                if chapter.content:
                    chapter.parsed_data = result
            
            novel.status = "completed"
            db.commit()
        except Exception as e:
            novel.status = "failed"
            db.commit()
    
    background_tasks.add_task(do_parse)
    
    return {"success": True, "message": "解析任务已启动"}


@router.get("/{novel_id}/chapters", response_model=dict)
async def list_chapters(novel_id: str, db: Session = Depends(get_db)):
    """获取章节列表"""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id).order_by(Chapter.number).all()
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
async def create_chapter(novel_id: str, data: dict, db: Session = Depends(get_db)):
    """创建章节"""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
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
    novel.chapter_count = db.query(Chapter).filter(Chapter.novel_id == novel_id).count() + 1
    
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
async def get_chapter(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    """获取章节详情"""
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
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
        }
    }


@router.put("/{novel_id}/chapters/{chapter_id}", response_model=dict)
async def update_chapter(
    novel_id: str, 
    chapter_id: str, 
    data: dict, 
    db: Session = Depends(get_db)
):
    """更新章节"""
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    
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
async def delete_chapter(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    """删除章节"""
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    db.delete(chapter)
    
    # 更新小说章节数
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if novel:
        novel.chapter_count = db.query(Chapter).filter(Chapter.novel_id == novel_id).count() - 1
    
    db.commit()
    
    return {"success": True, "message": "删除成功"}


@router.post("/{novel_id}/chapters/{chapter_id}/split", response_model=dict)
async def split_chapter(
    novel_id: str, 
    chapter_id: str, 
    db: Session = Depends(get_db)
):
    """
    使用小说配置的拆分提示词将章节拆分为分镜
    """
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
    
    # 调用 DeepSeek API 进行拆分
    result = await deepseek_service.split_chapter_with_prompt(
        chapter_title=chapter.title,
        chapter_content=chapter.content or "",
        prompt_template=prompt_template.template,
        word_count=50
    )
    
    # 保存解析结果到章节
    chapter.parsed_data = json.dumps(result, ensure_ascii=False)
    db.commit()
    
    return {
        "success": True,
        "data": result
    }
