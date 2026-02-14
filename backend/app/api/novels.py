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
                "generatingStatus": c.generating_status,
                "createdAt": c.created_at.isoformat() if c.created_at else None,
            }
            for c in characters
        ]
    }


@router.post("/{novel_id}/parse-characters", response_model=dict)
async def parse_characters_from_text(
    novel_id: str,
    background_tasks: BackgroundTasks,
    sync: bool = False,  # 添加同步模式参数
    db: Session = Depends(get_db)
):
    """
    使用 DeepSeek API 解析小说文本，自动提取角色信息
    
    参数:
    - sync: 是否同步执行（立即返回结果）
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
    
    if sync:
        # 同步模式：立即执行并返回结果
        await parse_characters_task(novel_id, full_text)
        
        # 获取解析后的角色列表
        characters = db.query(Character).filter(Character.novel_id == novel_id).all()
        return {
            "success": True,
            "message": f"成功解析 {len(characters)} 个角色",
            "data": [
                {
                    "id": c.id,
                    "name": c.name,
                    "description": c.description,
                    "appearance": c.appearance,
                }
                for c in characters
            ]
        }
    else:
        # 异步模式：后台执行
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
    import json
    
    db = SessionLocal()
    try:
        print(f"[解析任务] 开始解析小说 {novel_id} 的角色，文本长度: {len(text)}")
        
        # 调用 DeepSeek 解析文本
        result = await deepseek_service.parse_novel_text(text)
        
        print(f"[解析任务] DeepSeek 返回结果: {json.dumps(result, ensure_ascii=False)[:500]}...")
        
        if "error" in result:
            print(f"[解析任务] 解析失败: {result['error']}")
            return
        
        characters_data = result.get("characters", [])
        
        if not characters_data:
            print(f"[解析任务] 未识别到任何角色")
            return
        
        print(f"[解析任务] 识别到 {len(characters_data)} 个角色")
        
        # 创建角色
        created_count = 0
        for char_data in characters_data:
            name = char_data.get("name", "").strip()
            if not name:
                continue
                
            # 检查是否已存在
            existing = db.query(Character).filter(
                Character.novel_id == novel_id,
                Character.name == name
            ).first()
            
            if existing:
                # 更新现有角色
                existing.description = char_data.get("description", existing.description)
                existing.appearance = char_data.get("appearance", existing.appearance)
                print(f"[解析任务] 更新角色: {name}")
            else:
                # 创建新角色
                character = Character(
                    novel_id=novel_id,
                    name=name,
                    description=char_data.get("description", ""),
                    appearance=char_data.get("appearance", ""),
                )
                db.add(character)
                created_count += 1
                print(f"[解析任务] 创建角色: {name}")
        
        db.commit()
        print(f"[解析任务] 成功！新建 {created_count} 个角色，更新 {len(characters_data) - created_count} 个角色")
        
    except Exception as e:
        print(f"[解析任务] 异常: {e}")
        import traceback
        traceback.print_exc()
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
async def create_chapter(novel_id: str, data: dict, db: Session = Depends(get_db)):
    """创建章节"""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    db_chapter = Chapter(
        novel_id=novel_id,
        title=data.get('title', '未命名章节'),
        number=data.get('number', 1),
        content=data.get('content', ''),
    )
    db.add(db_chapter)
    
    db.commit()
    db.refresh(db_chapter)
    
    # 更新章节数
    novel.chapter_count = db.query(Chapter).filter(Chapter.novel_id == novel_id).count()
    db.commit()
    
    return {
        "success": True,
        "data": {
            "id": db_chapter.id,
            "novelId": db_chapter.novel_id,
            "number": db_chapter.number,
            "title": db_chapter.title,
            "status": db_chapter.status,
            "progress": db_chapter.progress,
            "content": db_chapter.content,
            "createdAt": db_chapter.created_at.isoformat() if db_chapter.created_at else None,
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
            "novelId": chapter.novel_id,
            "number": chapter.number,
            "title": chapter.title,
            "content": chapter.content,
            "status": chapter.status,
            "progress": chapter.progress,
            "parsedData": chapter.parsed_data,
            "characterImages": chapter.character_images,
            "shotImages": chapter.shot_images,
            "shotVideos": chapter.shot_videos,
            "finalVideo": chapter.final_video,
            "createdAt": chapter.created_at.isoformat() if chapter.created_at else None,
            "updatedAt": chapter.updated_at.isoformat() if chapter.updated_at else None,
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
    
    # 更新字段
    if "title" in data:
        chapter.title = data["title"]
    if "content" in data:
        chapter.content = data["content"]
    if "number" in data:
        chapter.number = data["number"]
    
    db.commit()
    db.refresh(chapter)
    
    return {
        "success": True,
        "data": {
            "id": chapter.id,
            "novelId": chapter.novel_id,
            "number": chapter.number,
            "title": chapter.title,
            "content": chapter.content,
            "status": chapter.status,
            "progress": chapter.progress,
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
