from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.novel import Novel, Chapter, Character
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
                "createdAt": n.created_at.isoformat() if n.created_at else None,
                "updatedAt": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in novels
        ]
    }


@router.post("/", response_model=dict)
async def create_novel(novel: NovelCreate, db: Session = Depends(get_db)):
    """创建新小说"""
    db_novel = Novel(
        title=novel.title,
        author=novel.author,
        description=novel.description,
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


@router.post("/import")
async def import_novel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """导入 TXT 小说文件"""
    content = await file.read()
    text = content.decode('utf-8')
    
    # 简单解析：第一行作为标题
    lines = text.strip().split('\n')
    title = lines[0][:50] if lines else "未命名"
    
    # 创建小说
    novel = Novel(
        title=title,
        description=f"从 {file.filename} 导入",
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    
    return {
        "success": True,
        "data": {
            "id": novel.id,
            "title": novel.title,
            "chapterCount": 0,
        }
    }


@router.get("/{novel_id}/characters", response_model=dict)
async def list_novel_characters(novel_id: str, db: Session = Depends(get_db)):
    """获取小说的所有角色"""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    characters = db.query(Character).filter(Character.novel_id == novel_id).all()
    return {
        "success": True,
        "data": [
            {
                "id": c.id,
                "novelId": c.novel_id,
                "name": c.name,
                "description": c.description,
                "appearance": c.appearance,
                "imageUrl": c.image_url,
                "createdAt": c.created_at.isoformat() if c.created_at else None,
            }
            for c in characters
        ]
    }


@router.post("/{novel_id}/parse-characters", response_model=dict)
async def parse_characters_from_text(
    novel_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    使用 DeepSeek API 解析小说文本，自动提取角色信息
    """
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 获取所有章节内容
    chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id).all()
    if not chapters:
        return {
            "success": False,
            "message": "小说没有章节内容，无法解析角色"
        }
    
    # 合并章节文本（限制长度）
    full_text = "\n\n".join([c.content for c in chapters if c.content])[:10000]
    
    if not full_text:
        return {
            "success": False,
            "message": "章节内容为空，无法解析"
        }
    
    # 后台任务解析角色
    background_tasks.add_task(
        parse_characters_task,
        novel_id,
        full_text
    )
    
    return {
        "success": True,
        "message": "角色解析任务已启动，请稍后查看"
    }


async def parse_characters_task(novel_id: str, text: str):
    """后台任务：解析小说文本提取角色"""
    from app.core.database import SessionLocal
    
    db = SessionLocal()
    try:
        # 调用 DeepSeek 解析文本
        result = await deepseek_service.parse_novel_text(text)
        
        if "error" in result:
            print(f"解析失败: {result['error']}")
            return
        
        characters_data = result.get("characters", [])
        
        # 创建角色
        for char_data in characters_data:
            # 检查是否已存在
            existing = db.query(Character).filter(
                Character.novel_id == novel_id,
                Character.name == char_data.get("name")
            ).first()
            
            if existing:
                # 更新现有角色
                existing.description = char_data.get("description", existing.description)
                existing.appearance = char_data.get("appearance", existing.appearance)
            else:
                # 创建新角色
                character = Character(
                    novel_id=novel_id,
                    name=char_data.get("name", "未命名"),
                    description=char_data.get("description", ""),
                    appearance=char_data.get("appearance", ""),
                )
                db.add(character)
        
        db.commit()
        print(f"成功解析并创建 {len(characters_data)} 个角色")
        
    except Exception as e:
        print(f"解析角色任务失败: {e}")
    finally:
        db.close()


@router.get("/{novel_id}/chapters", response_model=dict)
async def list_chapters(novel_id: str, db: Session = Depends(get_db)):
    """获取章节列表"""
    chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id).order_by(Chapter.number).all()
    return {
        "success": True,
        "data": [
            {
                "id": c.id,
                "novelId": c.novel_id,
                "number": c.number,
                "title": c.title,
                "status": c.status,
                "progress": c.progress,
            }
            for c in chapters
        ]
    }


@router.post("/{novel_id}/chapters", response_model=dict)
async def create_chapter(novel_id: str, chapter: ChapterCreate, db: Session = Depends(get_db)):
    """创建章节"""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    db_chapter = Chapter(
        novel_id=novel_id,
        title=chapter.title,
        number=chapter.number,
        content=chapter.content,
    )
    db.add(db_chapter)
    
    # 更新章节数
    novel.chapter_count = db.query(Chapter).filter(Chapter.novel_id == novel_id).count() + 1
    
    db.commit()
    db.refresh(db_chapter)
    return {
        "success": True,
        "data": {
            "id": db_chapter.id,
            "title": db_chapter.title,
            "status": db_chapter.status,
            "progress": db_chapter.progress,
        }
    }
