"""Novel-level merged video API."""
import json
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
from app.services.background_workers import persistent_job, worker_manager
from app.services.novel_video_merge_service import format_novel_video_merge, run_novel_video_merge_task
from app.services.file_storage import file_storage
from app.utils.path_utils import url_to_local_path


router = APIRouter()


class MergeChapterVideosRequest(BaseModel):
    chapter_ids: list[str] = Field(min_length=2)
    video_variant: Literal["draft", "hd"] = "draft"
    target_megapixels: float | None = None


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
    return {"success": True, "data": [format_novel_video_merge(task) for task in tasks]}


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
