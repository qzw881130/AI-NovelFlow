"""Novel-level merged video API."""
import json
import math
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Chapter, Novel
from app.models.task import Task
from app.repositories.chapter_repository import ChapterRepository
from app.repositories.workflow import WorkflowRepository
from app.services.background_workers import persistent_job, worker_manager
from app.services.novel_video_merge_service import format_novel_video_merge, run_novel_video_merge_task
from app.services.novel_video_cover_service import COVER_SIZES, enqueue_novel_video_cover_task, format_novel_video_cover
from app.services.task_service import TaskService
from app.services.file_storage import file_storage
from app.api.config import get_or_create_config
from app.utils.path_utils import url_to_local_path


router = APIRouter()


class MergeChapterVideosRequest(BaseModel):
    chapter_ids: list[str] = Field(min_length=2)
    video_variant: Literal["draft", "hd"] = "draft"
    target_megapixels: float | None = None


class GenerateNovelCoverRequest(BaseModel):
    frame_seconds: float = Field(ge=0)
    aspect_ratio: Literal["16:9", "9:16", "4:3", "1:1"] = "16:9"
    title: str | None = Field(default=None, max_length=100)
    author: str | None = Field(default=None, max_length=100)
    production: str | None = Field(default=None, max_length=80)


@router.post("/novels/{novel_id}/video-merges")
async def create_novel_video_merge(
    novel_id: str,
    request: MergeChapterVideosRequest,
    db: Session = Depends(get_db),
):
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter_ids = list(dict.fromkeys(request.chapter_ids))
    if len(chapter_ids) < 2:
        raise HTTPException(status_code=400, detail="至少需要选择两个章回视频")
    chapters = db.query(Chapter).filter(
        Chapter.novel_id == novel_id,
        Chapter.id.in_(chapter_ids),
    ).order_by(Chapter.number).all()
    if len(chapters) != len(chapter_ids):
        raise HTTPException(status_code=400, detail="选择的章回不存在或不属于当前小说")

    chapter_repo = ChapterRepository(db)
    if request.video_variant == "hd" and request.target_megapixels is None:
        raise HTTPException(status_code=400, detail="合并高清章回必须选择明确的目标 MP")
    snapshots = []
    for chapter in chapters:
        video_info = chapter_repo.get_final_chapter_video_info(chapter, request.video_variant, request.target_megapixels)
        video_url = (video_info or {}).get("hdChapterVideoUrl" if request.video_variant == "hd" else "chapterVideoUrl")
        if not video_url or not url_to_local_path(video_url):
            raise HTTPException(status_code=400, detail=f"第 {chapter.number} 章《{chapter.title}》没有可用的章回视频")
        snapshots.append({
            "id": chapter.id,
            "number": chapter.number,
            "title": chapter.title,
            "videoUrl": video_url,
            "chapterMergeTaskId": (video_info or {}).get("hdChapterVideoTaskId" if request.video_variant == "hd" else "chapterVideoTaskId"),
            "targetMegapixels": request.target_megapixels,
        })

    task = Task(
        type="novel_video",
        status="pending",
        progress=0,
        name=f"合并小说章回视频: {novel.title}",
        description=f"合并 {len(chapters)} 个章回视频",
        novel_id=novel_id,
        metadata_json=json.dumps({
            "chapter_ids": [chapter.id for chapter in chapters],
            "chapters": snapshots,
            "video_variant": request.video_variant,
            "target_megapixels": request.target_megapixels,
        }, ensure_ascii=False),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    payload = {"task_id": task.id}
    worker_manager.worker("novel_video").enqueue(persistent_job(
        task.id,
        "app.services.novel_video_merge_service:run_novel_video_merge_task",
        payload,
        lambda: run_novel_video_merge_task(**payload),
    ))
    return {"success": True, "data": format_novel_video_merge(task)}


@router.get("/novels/{novel_id}/video-merges")
def list_novel_video_merges(
    novel_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if not db.query(Novel.id).filter(Novel.id == novel_id).first():
        raise HTTPException(status_code=404, detail="小说不存在")
    tasks = db.query(Task).filter(
        Task.novel_id == novel_id,
        Task.type == "novel_video",
    ).order_by(Task.created_at.desc()).limit(limit).all()
    covers = db.query(Task).filter(
        Task.novel_id == novel_id, Task.type == "novel_video_cover",
        Task.parent_task_id.in_([task.id for task in tasks]),
    ).order_by(Task.created_at.desc(), Task.id.desc()).all() if tasks else []
    latest_covers = {}
    for cover in covers:
        latest_covers.setdefault(cover.parent_task_id, cover)
    return {"success": True, "data": [
        {**format_novel_video_merge(task), "cover": format_novel_video_cover(latest_covers.get(task.id))}
        for task in tasks
    ]}


@router.post("/novels/{novel_id}/video-merges/{task_id}/cover")
async def create_novel_video_cover(novel_id: str, task_id: str, request: GenerateNovelCoverRequest,
                                   db: Session = Depends(get_db)):
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    merge = db.query(Task).filter(Task.id == task_id, Task.novel_id == novel_id,
                                  Task.type == "novel_video", Task.status == "completed").first()
    if not novel or not merge or not merge.result_url:
        raise HTTPException(status_code=404, detail="已完成的章回合并视频不存在")
    video_path = url_to_local_path(merge.result_url)
    if not video_path or not Path(video_path).is_file():
        raise HTTPException(status_code=404, detail="章回合并视频文件不存在")
    merge_metadata = json.loads(merge.metadata_json or "{}")
    duration = merge_metadata.get("duration")
    if not math.isfinite(request.frame_seconds) or (duration and request.frame_seconds >= float(duration)):
        raise HTTPException(status_code=400, detail="选取的时间必须在视频时长范围内")
    active = db.query(Task.id).filter(Task.parent_task_id == task_id, Task.type == "novel_video_cover",
                                      Task.status.in_(["pending", "running"])).first()
    if active:
        raise HTTPException(status_code=409, detail="封面正在生成，请等待当前任务完成")
    workflow = WorkflowRepository(db).get_active_by_type("shot_scene")
    if not workflow:
        raise HTTPException(status_code=400, detail="请先启用分镜图生成（场景）工作流")
    valid, error = TaskService.validate_workflow_node_mapping(workflow, "shot_scene")
    if not valid:
        raise HTTPException(status_code=400, detail=error)
    config = get_or_create_config(db)
    title = (request.title if request.title is not None else novel.title or "").strip()
    author = (request.author if request.author is not None else novel.author or "").strip()
    production = (request.production if request.production is not None else config.cover_production or "旺仔有声小说").strip()
    if not title or not author or not production:
        raise HTTPException(status_code=400, detail="封面标题、原作者和制作均不能为空")
    cover = Task(
        type="novel_video_cover", status="pending", progress=0,
        name=f"生成视频封面: {novel.title}", novel_id=novel_id,
        parent_task_id=task_id, workflow_id=workflow.id, workflow_name=workflow.name,
        metadata_json=json.dumps({
            "frame_seconds": request.frame_seconds, "aspect_ratio": request.aspect_ratio,
            "title": title, "author": author, "production": production,
            "output_size": COVER_SIZES[request.aspect_ratio],
        }, ensure_ascii=False),
    )
    db.add(cover)
    db.commit()
    db.refresh(cover)
    enqueue_novel_video_cover_task(cover.id)
    return {"success": True, "data": format_novel_video_cover(cover)}


@router.get("/novels/{novel_id}/video-merges/{task_id}/cover/download")
def download_novel_video_cover(novel_id: str, task_id: str, db: Session = Depends(get_db)):
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    cover = db.query(Task).filter(
        Task.novel_id == novel_id, Task.parent_task_id == task_id,
        Task.type == "novel_video_cover", Task.status == "completed",
    ).order_by(Task.created_at.desc(), Task.id.desc()).first()
    if not cover or not cover.result_url:
        raise HTTPException(status_code=404, detail="视频封面不存在")
    local_path = url_to_local_path(cover.result_url)
    path = Path(local_path).resolve() if local_path else None
    if not path or not path.is_relative_to(file_storage.base_dir.resolve()) or not path.is_file():
        raise HTTPException(status_code=404, detail="视频封面文件不存在")
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", (novel.title or "").strip()).strip(". ")[:180] or "小说"
    return FileResponse(path, media_type="image/png", filename=f"{title}-视频封面.png")


@router.get("/novels/{novel_id}/video-merges/{task_id}/download")
def download_novel_video_merge(
    novel_id: str,
    task_id: str,
    db: Session = Depends(get_db),
):
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.novel_id == novel_id,
        Task.type == "novel_video",
        Task.status == "completed",
    ).first()
    if not task or not task.result_url:
        raise HTTPException(status_code=404, detail="合并视频不存在")

    local_path = url_to_local_path(task.result_url)
    base_dir = file_storage.base_dir.resolve()
    video_path = Path(local_path).resolve() if local_path else None
    if not video_path or not video_path.is_relative_to(base_dir) or not video_path.is_file():
        raise HTTPException(status_code=404, detail="合并视频文件不存在")

    try:
        metadata = json.loads(task.metadata_json or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    if metadata.get("video_variant") == "hd":
        target = metadata.get("target_megapixels")
        label = f"高清{target:g}MP" if isinstance(target, (int, float)) else "高清"
    else:
        label = "初稿"
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", (novel.title or "").strip()).strip(". ")[:180] or "小说"
    return FileResponse(video_path, media_type="video/mp4", filename=f"{title}-{label}.mp4")
