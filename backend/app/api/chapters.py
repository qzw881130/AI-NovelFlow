"""
章节路由 - 章节 CRUD 和批量导入相关接口
"""
import io
import re
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.repositories import NovelRepository, ChapterRepository, CharacterRepository, SceneRepository, PropRepository
from app.services.image_quality_review import current_image_reviews
from app.services.background_workers import persistent_job, worker_manager
from app.services.chapter_ai_split_service import (
    SPLIT_HANDLER, SPLIT_QUEUE_COUNT, format_split_batch, refresh_split_batch, run_chapter_ai_split_task,
)
from app.api.deps import get_novel_repo, get_chapter_repo, get_character_repo, get_scene_repo, get_prop_repo
from app.utils.time_utils import format_datetime
from app.utils.text_utils import detect_encoding, parse_chapters_from_text

router = APIRouter()


class BatchAiSplitRequest(BaseModel):
    chapter_ids: list[str] = Field(min_length=1, max_length=200)


def _safe_text_filename(name: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', (name or '').strip()).strip('. ')
    return (cleaned or fallback)[:180]


# ==================== 章节 CRUD ====================

@router.get("/{novel_id}/chapters", response_model=dict)
async def list_chapters(
    novel_id: str, 
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo), 
    chapter_repo: ChapterRepository = Depends(get_chapter_repo)
):
    """获取章节列表"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    chapters = chapter_repo.list_by_novel(novel_id)
    chapter_ids = [chapter.id for chapter in chapters]
    shot_image_stats = {
        chapter_id: {"generated": 0, "total": 0, "passed": 0, "warning": 0, "failed": 0}
        for chapter_id in chapter_ids
    }
    shot_video_stats = {
        chapter_id: {"completed": 0, "total": 0}
        for chapter_id in chapter_ids
    }
    estimated_durations = {}
    generated_images = []
    split_chapter_ids = set()
    if chapter_ids:
        for chapter_id, duration, image_url, image_task_id, video_url, video_status in db.query(
            Shot.chapter_id, Shot.duration, Shot.image_url, Shot.image_task_id,
            Shot.video_url, Shot.video_status,
        ).filter(Shot.chapter_id.in_(chapter_ids)).all():
            split_chapter_ids.add(chapter_id)
            estimated_durations[chapter_id] = estimated_durations.get(chapter_id, 0) + (duration or 0)
            stats = shot_image_stats[chapter_id]
            stats["total"] += 1
            video_stats = shot_video_stats[chapter_id]
            video_stats["total"] += 1
            if video_status == "completed" and video_url:
                video_stats["completed"] += 1
            if image_url:
                stats["generated"] += 1
                generated_images.append((chapter_id, image_task_id, image_url))

    # Use the same current-image projection as the generation page. A review for
    # an earlier image from the same task must not count for its replacement.
    for start in range(0, len(generated_images), 200):
        batch = generated_images[start:start + 200]
        reviews = current_image_reviews(db, [
            {"taskId": task_id, "imageUrl": image_url}
            for _, task_id, image_url in batch
        ])
        for (chapter_id, _, _), review in zip(batch, reviews):
            key = {"PASS": "passed", "WARNING": "warning", "FAIL": "failed"}.get(review["qualityStatus"])
            if key:
                shot_image_stats[chapter_id][key] += 1
    return {
        "success": True,
        "data": [
            {**chapter_repo.to_response(chapter),
             "aiSplitCompleted": bool(chapter.parsed_data) and chapter.id in split_chapter_ids,
             "estimatedDuration": estimated_durations.get(chapter.id),
             "shotImageStats": shot_image_stats[chapter.id],
             "shotVideoStats": shot_video_stats[chapter.id]}
            for chapter in chapters
        ]
    }


@router.post("/{novel_id}/chapter-ai-split-batches")
async def create_chapter_ai_split_batch(novel_id: str, request: BatchAiSplitRequest, db: Session = Depends(get_db)):
    novel = db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    chapter_ids = list(dict.fromkeys(request.chapter_ids))
    chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id, Chapter.id.in_(chapter_ids)).all()
    if len(chapters) != len(chapter_ids):
        raise HTTPException(status_code=400, detail="选择的章回不存在或不属于当前小说")
    active_batches = db.query(Task).filter(
        Task.novel_id == novel_id, Task.type == "chapter_ai_split_batch",
        Task.status.in_(["pending", "running"]),
    ).all()
    for active in active_batches:
        refresh_split_batch(db, active.id)
    if any(active.status in {"pending", "running"} for active in active_batches):
        raise HTTPException(status_code=409, detail="当前小说已有正在进行的批量 AI 拆分")

    by_id = {chapter.id: chapter for chapter in chapters}
    ordered = [by_id[chapter_id] for chapter_id in chapter_ids]
    batch = Task(type="chapter_ai_split_batch", status="running", novel_id=novel_id,
                 name=f"批量 AI 拆分: {novel.title}", progress=0,
                 current_step=f"等待拆分 {len(ordered)} 个章回", created_at=datetime.utcnow(), started_at=datetime.utcnow())
    db.add(batch)
    db.flush()
    children = [Task(type="chapter_ai_split", status="pending", novel_id=novel_id,
                     chapter_id=chapter.id, parent_task_id=batch.id, batch_order=index,
                     name=chapter.title, progress=0, current_step="等待后台拆分")
                for index, chapter in enumerate(ordered)]
    db.add_all(children)
    db.commit()

    for index, child in enumerate(children):
        payload = {"task_id": child.id}
        try:
            worker_manager.worker(f"chapter_ai_split_{index % SPLIT_QUEUE_COUNT}").enqueue(persistent_job(
                child.id, SPLIT_HANDLER, payload, lambda task_id=child.id: run_chapter_ai_split_task(task_id),
            ), db=db)
        except Exception as exc:
            db.rollback()
            child = db.get(Task, child.id)
            child.status = "failed"
            child.error_message = f"加入后台队列失败: {exc}"
            child.completed_at = datetime.utcnow()
            db.commit()
    refresh_split_batch(db, batch.id)
    return {"success": True, "data": format_split_batch(batch, children)}


@router.get("/{novel_id}/chapter-ai-split-batches")
def list_chapter_ai_split_batches(novel_id: str, db: Session = Depends(get_db)):
    if not db.get(Novel, novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    batches = db.query(Task).filter(
        Task.novel_id == novel_id, Task.type == "chapter_ai_split_batch",
    ).order_by(Task.created_at.desc(), Task.id.desc()).limit(20).all()
    children = db.query(Task).filter(
        Task.parent_task_id.in_([batch.id for batch in batches]), Task.type == "chapter_ai_split",
    ).all() if batches else []
    by_batch = {batch.id: [] for batch in batches}
    for child in children:
        by_batch[child.parent_task_id].append(child)
    return {"success": True, "data": [format_split_batch(batch, by_batch[batch.id]) for batch in batches]}


@router.post("/{novel_id}/chapters/download-originals")
async def download_originals(
    novel_id: str,
    data: dict,
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
):
    """将选中的章回原文分别写入 TXT 并打包下载。"""
    if not novel_repo.get_by_id(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    chapter_ids = data.get("chapter_ids")
    if not isinstance(chapter_ids, list) or not chapter_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个章回")

    chapters = chapter_repo.list_by_ids(novel_id, chapter_ids)
    chapter_by_id = {chapter.id: chapter for chapter in chapters}
    if any(chapter_id not in chapter_by_id for chapter_id in chapter_ids):
        raise HTTPException(status_code=404, detail="部分章回不存在或不属于当前小说")

    archive = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for chapter in sorted(chapters, key=lambda item: (item.number, item.id)):
            base_name = _safe_text_filename(f"第{chapter.number}章 {chapter.title}", f"chapter-{chapter.number}")
            filename = f"{base_name}.txt"
            suffix = 2
            while filename in used_names:
                filename = f"{base_name} ({suffix}).txt"
                suffix += 1
            used_names.add(filename)
            zip_file.writestr(filename, f"{chapter.title}\n\n{chapter.content or ''}".encode("utf-8-sig"))

    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=novel-originals.zip"},
    )


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
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    include_shots: bool = True
):
    """获取章节详情"""
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    return {
        "success": True,
        "data": chapter_repo.to_detail_response(chapter, include_shots=include_shots)
    }


@router.get("/{novel_id}/chapters/{chapter_id}/merge-video-status", response_model=dict)
async def get_chapter_merge_video_status(
    novel_id: str,
    chapter_id: str,
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
):
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"success": True, "data": chapter_repo.get_chapter_video_merge_status(chapter)}


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
    from app.services.novel_service import NovelService
    
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
    from app.services.novel_service import NovelService

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


@router.post("/{novel_id}/chapters/{chapter_id}/parse-props/", response_model=dict)
async def parse_chapter_props(
    novel_id: str,
    chapter_id: str,
    is_incremental: bool = True,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    prop_repo: PropRepository = Depends(get_prop_repo)
):
    """解析单章节内容，提取道具信息（支持增量更新）"""
    from app.services.novel_service import NovelService

    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)

    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    if not chapter.content:
        return {"success": False, "message": "章节内容为空"}

    service = NovelService(db)
    return await service.parse_props(
        novel_id=novel_id,
        chapters=[chapter],
        start_chapter=chapter.number,
        end_chapter=chapter.number,
        is_incremental=is_incremental,
        prop_repo=prop_repo
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
    scene_repo: SceneRepository = Depends(get_scene_repo),
    prop_repo: PropRepository = Depends(get_prop_repo)
):
    """使用小说配置的拆分提示词将章节拆分为分镜"""
    from app.services.novel_service import NovelService
    
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    # 获取当前小说的所有角色、场景和道具列表
    character_names = character_repo.get_names_by_novel(novel_id)
    scene_names = scene_repo.get_names_by_novel(novel_id)
    prop_names = prop_repo.get_visual_names_by_novel(novel_id)
    
    service = NovelService(db)
    return await service.split_chapter(
        novel=novel,
        chapter=chapter,
        character_names=character_names,
        scene_names=scene_names,
        prop_names=prop_names
    )


# ==================== 批量导入 ====================

@router.post("/{novel_id}/chapters/batch-import/preview", response_model=dict)
async def batch_import_preview(
    novel_id: str,
    file: UploadFile = File(...),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo)
):
    """批量导入预览：解析 TXT 文件但不入库，返回章节列表及操作类型。"""
    # 校验文件扩展名
    if not file.filename or not file.filename.lower().endswith('.txt'):
        raise HTTPException(status_code=400, detail="仅支持 .txt 格式文件")

    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 读取文件内容
    raw_bytes = await file.read()
    if not raw_bytes:
        return {
            "success": True,
            "data": {
                "chapters": [],
                "summary": {"total": 0, "new": 0, "replace": 0},
                "errors": [],
            }
        }

    encoding = detect_encoding(raw_bytes)
    text = raw_bytes.decode(encoding, errors='replace')

    # 解析章节
    chapters, errors = parse_chapters_from_text(text)

    # 获取已有章节号
    existing_chapters = chapter_repo.list_by_novel(novel_id)
    existing_numbers = {c.number for c in existing_chapters}

    # 计算 action 类型
    preview_chapters = []
    new_count = 0
    replace_count = 0
    for ch in chapters:
        action = "replace" if ch['number'] in existing_numbers else "new"
        if action == "new":
            new_count += 1
        else:
            replace_count += 1
        preview_chapters.append({
            "number": ch['number'],
            "title": ch['title'],
            "content_length": len(ch['content']),
            "action": action,
        })

    return {
        "success": True,
        "data": {
            "chapters": preview_chapters,
            "summary": {
                "total": len(preview_chapters),
                "new": new_count,
                "replace": replace_count,
            },
            "errors": errors,
        }
    }


@router.post("/{novel_id}/chapters/batch-import", response_model=dict)
async def batch_import_chapters(
    novel_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo)
):
    """批量导入执行：解析 TXT 文件并执行 bulk_upsert。"""
    # 校验文件扩展名
    if not file.filename or not file.filename.lower().endswith('.txt'):
        raise HTTPException(status_code=400, detail="仅支持 .txt 格式文件")

    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 读取文件内容
    raw_bytes = await file.read()
    if not raw_bytes:
        return {
            "success": True,
            "data": {
                "total": 0,
                "created": 0,
                "updated": 0,
                "failed": 0,
                "errors": [],
                "chapters": [],
            },
            "message": "文件为空",
        }

    encoding = detect_encoding(raw_bytes)
    text = raw_bytes.decode(encoding, errors='replace')

    # 解析章节
    chapters, parse_errors = parse_chapters_from_text(text)

    # 完全无法解析章节
    if not chapters:
        return {
            "success": False,
            "message": "无法解析章节，请检查文件格式",
            "data": {"errors": parse_errors},
        }

    # 执行批量 upsert
    result = chapter_repo.bulk_upsert(novel_id, chapters)

    # 合并解析错误和 upsert 错误
    all_errors = parse_errors + result['errors']

    success_count = result['created'] + result['updated']
    failed_count = result['failed']

    # 构建消息
    if failed_count == 0:
        message = f"导入完成：成功 {success_count} 个"
    else:
        message = f"导入完成：成功 {success_count} 个，失败 {failed_count} 个"

    return {
        "success": True,
        "data": {
            "total": len(chapters),
            "created": result['created'],
            "updated": result['updated'],
            "failed": failed_count,
            "errors": all_errors,
            "chapters": result['chapters'],
        },
        "message": message,
    }
