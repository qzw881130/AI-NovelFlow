"""Novel chapter background-music tasks."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Chapter, Novel
from app.models.task import Task
from app.services.background_music_service import TASK_TYPE, enqueue_background_music_task, format_background_music
from app.utils.path_utils import url_to_local_path


router = APIRouter()


class BatchBackgroundMusicRequest(BaseModel):
    chapter_ids: list[str] = Field(min_length=1)


@router.get("/novels/{novel_id}/background-music")
def list_background_music(novel_id: str, db: Session = Depends(get_db)):
    if not db.query(Novel.id).filter(Novel.id == novel_id).first():
        raise HTTPException(status_code=404, detail="小说不存在")
    chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id).all()
    by_id = {chapter.id: chapter for chapter in chapters}
    tasks = db.query(Task).filter(Task.novel_id == novel_id, Task.type == TASK_TYPE).order_by(
        Task.created_at.desc(), Task.id.desc()).all()
    latest = {}
    for task in tasks:
        latest.setdefault(task.chapter_id, task)
    return {"success": True, "data": {
        chapter_id: format_background_music(task, by_id.get(chapter_id))
        for chapter_id, task in latest.items() if chapter_id in by_id
    }}


@router.post("/novels/{novel_id}/background-music")
async def batch_generate_background_music(novel_id: str, request: BatchBackgroundMusicRequest,
                                          db: Session = Depends(get_db)):
    if not db.query(Novel.id).filter(Novel.id == novel_id).first():
        raise HTTPException(status_code=404, detail="小说不存在")
    chapter_ids = list(dict.fromkeys(request.chapter_ids))
    chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id, Chapter.id.in_(chapter_ids)).all()
    if len(chapters) != len(chapter_ids):
        raise HTTPException(status_code=400, detail="选择的章回不存在或不属于当前小说")
    for chapter in chapters:
        if not chapter.final_video or not url_to_local_path(chapter.final_video):
            raise HTTPException(status_code=400, detail=f"第 {chapter.number} 章没有可用的初稿视频")
    active = db.query(Task).filter(Task.type == TASK_TYPE, Task.novel_id == novel_id,
        Task.chapter_id.in_(chapter_ids), Task.status.in_(["pending", "running"])).first()
    if active:
        raise HTTPException(status_code=409, detail="所选章回已有背景音乐任务在运行")
    tasks = []
    for chapter in sorted(chapters, key=lambda item: item.number):
        task = Task(type=TASK_TYPE, status="pending", progress=0, novel_id=novel_id,
            chapter_id=chapter.id, name=f"第 {chapter.number} 章背景音乐：{chapter.title}",
            description="LLM 规划配乐区间并由当前背景音乐工作流生成纯器乐候选",
            metadata_json=json.dumps({"source_video_url": chapter.final_video}, ensure_ascii=False))
        db.add(task)
        tasks.append(task)
    db.commit()
    for task in tasks:
        db.refresh(task)
        enqueue_background_music_task(task.id)
    return {"success": True, "data": [format_background_music(task) for task in tasks]}
