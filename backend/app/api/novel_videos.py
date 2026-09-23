"""Novel-level merged video API."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Chapter, Novel
from app.models.task import Task
from app.repositories.chapter_repository import ChapterRepository
from app.services.background_workers import worker_manager
from app.services.novel_video_merge_service import format_novel_video_merge, run_novel_video_merge_task
from app.utils.path_utils import url_to_local_path


router = APIRouter()


class MergeChapterVideosRequest(BaseModel):
    chapter_ids: list[str] = Field(min_length=2)


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
    snapshots = []
    for chapter in chapters:
        video_info = chapter_repo.get_final_chapter_video_info(chapter)
        video_url = (video_info or {}).get("chapterVideoUrl")
        if not video_url or not url_to_local_path(video_url):
            raise HTTPException(status_code=400, detail=f"第 {chapter.number} 章《{chapter.title}》没有可用的章回视频")
        snapshots.append({
            "id": chapter.id,
            "number": chapter.number,
            "title": chapter.title,
            "videoUrl": video_url,
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
        }, ensure_ascii=False),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    worker_manager.worker("novel_video").enqueue(lambda: run_novel_video_merge_task(task.id))
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
