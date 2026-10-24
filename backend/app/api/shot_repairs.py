"""Queue and inspect review-gated main storyboard repairs."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.services.shot_image_repair_service import REPAIR_TASK_TYPE, enqueue_shot_image_repair

router = APIRouter()


def _response(task: Task | None):
    if not task:
        return None
    return {"taskId": task.id, "status": task.status, "progress": task.progress,
            "currentStep": task.current_step, "errorMessage": task.error_message,
            "resultUrl": task.result_url, "sourceTaskId": task.source_task_id}


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/repair-image", status_code=202)
async def queue_shot_repair(novel_id: str, chapter_id: str, shot_id: str, db: Session = Depends(get_db)):
    try:
        task = enqueue_shot_image_repair(db, novel_id, chapter_id, shot_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "data": _response(task)}


@router.get("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/repair-image")
def latest_shot_repair(novel_id: str, chapter_id: str, shot_id: str, db: Session = Depends(get_db)):
    chapter, shot = db.get(Chapter, chapter_id), db.get(Shot, shot_id)
    if not chapter or chapter.novel_id != novel_id or not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")
    task = db.query(Task).filter(Task.type == REPAIR_TASK_TYPE, Task.shot_id == shot_id).order_by(
        Task.created_at.desc(), Task.id.desc()).first()
    return {"success": True, "data": _response(task)}
