import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.novel import Novel, Chapter, Character
from app.models.prompt_template import PromptTemplate
from app.models.task import Task
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


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/generate", response_model=dict)
async def generate_shot_image(
    novel_id: str,
    chapter_id: str,
    shot_index: int,  # 1-based index
    background_tasks: BackgroundTasks,
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
    
    # 后台执行生成
    background_tasks.add_task(
        generate_shot_task,
        task.id,
        novel_id,
        chapter_id,
        shot_index,
        shot_description,
        workflow.id
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
        
        # 记录工作流配置
        task.workflow_json = workflow.workflow_json
        task.prompt_text = shot_description
        db.commit()
        
        # 合并角色图片
        character_reference_path = None
        if shot_characters:
            task.current_step = f"合并角色图片: {', '.join(shot_characters)}"
            db.commit()
            
            # 获取角色图片路径
            character_images = []
            for char_name in shot_characters:
                character = db.query(Character).filter(
                    Character.novel_id == novel_id,
                    Character.name == char_name
                ).first()
                if character and character.image_url:
                    # 从 URL 提取本地路径
                    char_path = character.image_url.replace("/api/files/", "")
                    # 转换为绝对路径
                    full_path = os.path.join(os.path.dirname(__file__), "..", "..", "user_story", char_path)
                    full_path = os.path.abspath(full_path)
                    if os.path.exists(full_path):
                        character_images.append((char_name, full_path))
                        print(f"[ShotTask {task_id}] Found character image: {char_name} -> {full_path}")
            
            if character_images:
                # 创建合并图片目录
                story_dir = file_storage._get_story_dir(novel_id)
                merged_dir = story_dir / "merged_characters"
                merged_dir.mkdir(parents=True, exist_ok=True)
                
                # 生成合并图片文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                merged_filename = f"shot_{shot_index:03d}_{timestamp}_characters.png"
                merged_path = merged_dir / merged_filename
                
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
                    
                    # 加载所有图片
                    images = []
                    for char_name, img_path in character_images:
                        img = Image.open(img_path)
                        images.append((char_name, img))
                    
                    # 设置单元格大小
                    cell_width = 256
                    cell_height = 256
                    name_height = 30
                    padding = 10
                    
                    # 创建画布
                    canvas_width = cols * (cell_width + padding) + padding
                    canvas_height = rows * (cell_height + name_height + padding) + padding
                    canvas = Image.new('RGB', (canvas_width, canvas_height), (255, 255, 255))
                    
                    # 绘制每个角色
                    draw = ImageDraw.Draw(canvas)
                    
                    # 尝试加载字体，失败则使用默认
                    try:
                        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 16)
                    except:
                        font = ImageFont.load_default()
                    
                    for idx, (char_name, img) in enumerate(images):
                        col = idx % cols
                        row = idx // cols
                        x = padding + col * (cell_width + padding)
                        y = padding + row * (cell_height + name_height + padding)
                        
                        # 缩放图片保持比例
                        img.thumbnail((cell_width, cell_height), Image.LANCZOS)
                        
                        # 居中放置
                        img_x = x + (cell_width - img.width) // 2
                        img_y = y + (cell_height - img.height) // 2
                        canvas.paste(img, (img_x, img_y))
                        
                        # 绘制角色名称
                        text_bbox = draw.textbbox((0, 0), char_name, font=font)
                        text_width = text_bbox[2] - text_bbox[0]
                        text_x = x + (cell_width - text_width) // 2
                        text_y = y + cell_height + 5
                        draw.text((text_x, text_y), char_name, fill=(51, 51, 51), font=font)
                    
                    # 保存合并图片
                    canvas.save(merged_path, "PNG")
                    character_reference_path = str(merged_path)
                    print(f"[ShotTask {task_id}] Merged character image saved: {merged_path}")
                    task.current_step = f"已合并 {len(character_images)} 个角色图片"
                    db.commit()
                    
                except Exception as e:
                    print(f"[ShotTask {task_id}] Failed to merge character images: {e}")
                    import traceback
                    traceback.print_exc()
                    task.current_step = "角色图片合并失败，继续生成..."
                    db.commit()
        
        # 调用 ComfyUI 生成图片
        task.current_step = "正在调用 ComfyUI 生成图片..."
        task.progress = 30
        db.commit()
        
        result = await comfyui_service.generate_shot_image_with_workflow(
            prompt=shot_description,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            character_reference_path=character_reference_path
        )
        
        print(f"[ShotTask {task_id}] Generation result: {result}")
        
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
                image_type="shot"
            )
            
            if local_path:
                # 构建本地可访问的URL
                relative_path = local_path.replace(str(file_storage.base_dir), "")
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
