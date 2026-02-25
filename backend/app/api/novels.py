import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.novel import Novel, Chapter, Character
from app.models.prompt_template import PromptTemplate
from app.models.task import Task
from app.models.workflow import Workflow
from app.schemas.novel import NovelCreate, NovelResponse, ChapterCreate, ChapterResponse
from app.services.llm_service import LLMService
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.services.novel_service import NovelService, generate_shot_task, generate_shot_video_task, generate_transition_video_task
from app.services.task_service import TaskService
from app.repositories import NovelRepository, ChapterRepository, CharacterRepository, SceneRepository
from app.core.utils import format_datetime

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


# ==================== 章节 CRUD ====================

@router.get("/{novel_id}/chapters", response_model=dict)
async def list_chapters(
    novel_id: str, 
    novel_repo: NovelRepository = Depends(get_novel_repo), 
    chapter_repo: ChapterRepository = Depends(get_chapter_repo)
):
    """获取章节列表"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapters = chapter_repo.list_by_novel(novel_id)
    return {
        "success": True,
        "data": [chapter_repo.to_response(c) for c in chapters]
    }


@router.post("/{novel_id}/chapters", response_model=dict)
async def create_chapter(
    novel_id: str, 
    data: dict, 
    db: Session = Depends(get_db), 
    novel_repo: NovelRepository = Depends(get_novel_repo), 
    chapter_repo: ChapterRepository = Depends(get_chapter_repo)
):
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
    novel.chapter_count = chapter_repo.count_by_novel(novel_id) + 1
    
    db.commit()
    db.refresh(chapter)
    
    return {
        "success": True,
        "data": chapter_repo.to_response(chapter)
    }


@router.get("/{novel_id}/chapters/{chapter_id}", response_model=dict)
async def get_chapter(
    novel_id: str, 
    chapter_id: str, 
    chapter_repo: ChapterRepository = Depends(get_chapter_repo)
):
    """获取章节详情"""
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    return {
        "success": True,
        "data": chapter_repo.to_detail_response(chapter)
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
            **chapter_repo.to_response(chapter),
            "content": chapter.content,
            "parsedData": chapter.parsed_data,
            "updatedAt": format_datetime(chapter.updated_at),
        }
    }


@router.delete("/{novel_id}/chapters/{chapter_id}")
async def delete_chapter(
    novel_id: str, 
    chapter_id: str, 
    db: Session = Depends(get_db), 
    novel_repo: NovelRepository = Depends(get_novel_repo), 
    chapter_repo: ChapterRepository = Depends(get_chapter_repo)
):
    """删除章节"""
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    db.delete(chapter)
    
    # 更新小说章节数
    novel = novel_repo.get_by_id(novel_id)
    if novel:
        novel.chapter_count = chapter_repo.count_by_novel(novel_id) - 1
    
    db.commit()
    
    return {"success": True, "message": "删除成功"}


# ==================== 章节角色/场景解析 ====================

@router.post("/{novel_id}/chapters/{chapter_id}/parse-characters/", response_model=dict)
async def parse_chapter_characters(
    novel_id: str,
    chapter_id: str,
    is_incremental: bool = True,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    character_repo: CharacterRepository = Depends(get_character_repo)
):
    """解析单章节内容，提取角色信息（支持增量更新）"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    if not chapter.content:
        return {"success": False, "message": "章节内容为空"}
    
    service = NovelService(db)
    return await service.parse_characters(
        novel_id=novel_id,
        chapters=[chapter],
        start_chapter=chapter.number,
        end_chapter=chapter.number,
        is_incremental=is_incremental,
        character_repo=character_repo
    )


@router.post("/{novel_id}/chapters/{chapter_id}/parse-scenes/", response_model=dict)
async def parse_chapter_scenes(
    novel_id: str,
    chapter_id: str,
    is_incremental: bool = True,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    scene_repo: SceneRepository = Depends(get_scene_repo)
):
    """解析单章节内容，提取场景信息（支持增量更新）"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    if not chapter.content:
        return {"success": False, "message": "章节内容为空"}
    
    service = NovelService(db)
    return await service.parse_scenes(
        novel_id=novel_id,
        chapter=chapter,
        is_incremental=is_incremental,
        scene_repo=scene_repo
    )


# ==================== 章节拆分 ====================

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
    """使用小说配置的拆分提示词将章节拆分为分镜"""
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 获取当前小说的所有角色和场景列表
    character_names = character_repo.get_names_by_novel(novel_id)
    scene_names = scene_repo.get_names_by_novel(novel_id)
    
    service = NovelService(db)
    return await service.split_chapter(
        novel=novel,
        chapter=chapter,
        character_names=character_names,
        scene_names=scene_names
    )


# ==================== 分镜图生成 ====================

@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/generate", response_model=dict)
async def generate_shot_image(
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    db: Session = Depends(get_db)
):
    """为指定分镜生成图片（创建后台任务）"""
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
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(workflow, "shot")
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    # 清除旧的图片数据和文件
    file_storage.delete_shot_image(novel_id, chapter_id, shot_index)
    
    shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
    if isinstance(shot_images, list) and len(shot_images) >= shot_index:
        shot_images[shot_index - 1] = None
        chapter.shot_images = json.dumps(shot_images, ensure_ascii=False)
    
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
    
    # 启动后台任务
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


# ==================== 分镜视频生成 ====================

@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/generate-video", response_model=dict)
async def generate_shot_video(
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    db: Session = Depends(get_db)
):
    """为指定分镜生成视频（基于已生成的分镜图片）"""
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
    shot_duration = shot.get("duration", 4)
    
    # 检查是否有已生成的分镜图片
    shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
    shot_image_url = None
    
    if isinstance(shot_images, list) and len(shot_images) >= shot_index:
        shot_image_url = shot_images[shot_index - 1]
    
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
    
    # 清除该分镜的旧视频记录
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
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(workflow, "video")
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


# ==================== 转场视频生成 ====================

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
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    from_index = data.get("from_index")
    to_index = data.get("to_index")
    frame_count = data.get("frame_count", 49)
    workflow_id = data.get("workflow_id")
    
    if not from_index or not to_index:
        raise HTTPException(status_code=400, detail="缺少 from_index 或 to_index")
    
    # 解析分镜数据
    parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {}
    shots = parsed_data.get("shots", [])
    
    if from_index < 1 or to_index > len(shots) or from_index >= to_index:
        raise HTTPException(status_code=400, detail="无效的分镜索引")
    
    # 获取分镜视频
    shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
    
    first_video = shot_videos[from_index - 1] if from_index <= len(shot_videos) else None
    second_video = shot_videos[to_index - 1] if to_index <= len(shot_videos) else None
    
    if not first_video or not second_video:
        raise HTTPException(status_code=400, detail="分镜视频尚未生成，请先生成分镜视频")
    
    # 检查是否已有进行中的转场视频任务
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
    if workflow_id:
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise HTTPException(status_code=400, detail="指定的工作流不存在")
    else:
        workflow = db.query(Workflow).filter(
            Workflow.type == "transition",
            Workflow.is_active == True
        ).first()
    
    if not workflow:
        raise HTTPException(status_code=400, detail="未配置转场视频工作流，请在系统设置中配置")
    
    # 验证工作流节点映射配置
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(workflow, "transition")
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
    """一键生成所有相邻分镜之间的转场视频"""
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
    
    # 获取分镜视频
    shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
    
    if len(shot_videos) < len(shots):
        raise HTTPException(status_code=400, detail="部分分镜视频尚未生成，请先生成所有分镜视频")
    
    frame_count = data.get("frame_count", 49)
    workflow_id = data.get("workflow_id")
    
    # 获取转场视频工作流
    if workflow_id:
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise HTTPException(status_code=400, detail="指定的工作流不存在")
    else:
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


# ==================== 素材下载与合并 ====================

@router.get("/{novel_id}/chapters/{chapter_id}/download-materials", response_model=dict)
async def download_chapter_materials(
    novel_id: str,
    chapter_id: str,
    db: Session = Depends(get_db)
):
    """下载章节素材 ZIP 包"""
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
    """合并章节视频"""
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
        if video_url and video_url.startswith("/api/files/"):
            full_path = NovelService.url_to_local_path(video_url)
            if full_path:
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
                full_path = NovelService.url_to_local_path(trans_url)
                if full_path:
                    trans_paths.append(full_path)
                else:
                    trans_paths.append(None)
            else:
                trans_paths.append(None)
    
    # 生成输出路径
    import os
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


# ==================== 资源管理 ====================

@router.post("/{novel_id}/chapters/{chapter_id}/clear-resources", response_model=dict)
async def clear_chapter_resources(
    novel_id: str,
    chapter_id: str,
    db: Session = Depends(get_db)
):
    """清除章节的所有生成资源（用于重新拆分分镜头前）"""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 删除物理文件
    print(f"[ClearResources] Deleting physical files for chapter {chapter_id}")
    file_deleted = file_storage.delete_chapter_directory(novel_id, chapter_id)
    
    # 清除数据库记录
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


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/upload-image", response_model=dict)
async def upload_shot_image(
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """上传分镜图片"""
    # 验证文件类型
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400, 
            detail=f"不支持的文件类型: {file.content_type}，仅支持 PNG, JPG, WEBP"
        )
    
    # 获取章节
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.novel_id == novel_id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 解析章节数据
    if not chapter.parsed_data:
        raise HTTPException(status_code=400, detail="章节未拆分，请先进行AI拆分")
    
    parsed_data = json.loads(chapter.parsed_data) if isinstance(chapter.parsed_data, str) else chapter.parsed_data
    shots = parsed_data.get("shots", [])
    
    if shot_index < 1 or shot_index > len(shots):
        raise HTTPException(status_code=400, detail="分镜索引超出范围")
    
    try:
        # 删除旧图片
        file_storage.delete_shot_image(novel_id, chapter_id, shot_index)
        
        # 获取保存路径
        file_path = file_storage.get_shot_image_path(
            novel_id=novel_id,
            chapter_id=chapter_id,
            shot_number=shot_index
        )
        
        # 保存文件
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 计算访问URL
        relative_path = file_path.relative_to(file_storage.base_dir)
        image_url = f"/api/files/{relative_path}"
        
        # 更新 parsed_data
        parsed_data["shots"][shot_index - 1]["image_url"] = image_url
        parsed_data["shots"][shot_index - 1]["image_path"] = str(file_path)
        chapter.parsed_data = json.dumps(parsed_data, ensure_ascii=False)
        
        # 更新 shot_images 数组
        shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
        while len(shot_images) < shot_index:
            shot_images.append(None)
        shot_images[shot_index - 1] = image_url
        chapter.shot_images = json.dumps(shot_images, ensure_ascii=False)
        
        db.commit()
        db.refresh(chapter)
        
        return {
            "success": True,
            "data": {
                "shotIndex": shot_index,
                "imageUrl": image_url,
                "parsedData": parsed_data
            },
            "message": "分镜图片上传成功"
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")
