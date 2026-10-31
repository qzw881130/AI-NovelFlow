"""Durable, bounded parallel execution for batch chapter AI splitting."""
import asyncio
import json
from datetime import datetime

from app.core.database import SessionLocal
from app.models.novel import Chapter, Novel
from app.models.task import Task
from app.repositories import CharacterRepository, PropRepository, SceneRepository
from app.services.novel_service import NovelService


SPLIT_QUEUE_COUNT = 3
SPLIT_HANDLER = "app.services.chapter_ai_split_service:run_chapter_ai_split_task"
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def format_split_batch(batch: Task, children: list[Task]) -> dict:
    completed = sum(task.status == "completed" for task in children)
    failed = sum(task.status in {"failed", "cancelled"} for task in children)
    running = sum(task.status == "running" for task in children)
    expected = json.loads(batch.metadata_json or "{}").get("expected_count") or 0
    total = max(len(children), expected)
    if batch.status == "failed" and len(children) < total:
        status = "failed"
    elif total and completed + failed == total and failed:
        status = "failed"
    elif total and completed == total:
        status = "completed"
    else:
        status = "running"
    return {
        "id": batch.id, "status": status, "total": total, "completed": completed,
        "failed": failed, "running": running, "pending": total - completed - failed - running,
        "createdAt": batch.created_at.isoformat() if batch.created_at else None,
        "chapters": [
            {"taskId": task.id, "chapterId": task.chapter_id, "title": task.name,
             "status": task.status, "errorMessage": task.error_message}
            for task in sorted(children, key=lambda item: (item.batch_order or 0, item.id))
        ],
    }


def refresh_split_batch(db, batch_id: str | None) -> None:
    if not batch_id:
        return
    batch = db.get(Task, batch_id)
    if not batch or batch.status == "cancelled":
        return
    child_type = "grid_chapter_plan" if batch.type == "grid_chapter_plan_batch" else "chapter_ai_split"
    children = db.query(Task).filter(Task.parent_task_id == batch_id, Task.type == child_type).all()
    if not children:
        return
    summary = format_split_batch(batch, children)
    batch.status = summary["status"]
    batch.progress = round((summary["completed"] + summary["failed"]) * 100 / summary["total"])
    batch.current_step = f"成功 {summary['completed']}，失败 {summary['failed']}，进行中 {summary['running']}"
    if batch.status in TERMINAL_STATUSES:
        batch.completed_at = batch.completed_at or datetime.utcnow()
    db.commit()


async def run_chapter_ai_split_task(task_id: str) -> None:
    db = SessionLocal()
    parent_id = None
    try:
        task = db.query(Task).filter(Task.id == task_id, Task.type == "chapter_ai_split").first()
        if not task or task.status in TERMINAL_STATUSES:
            return
        parent_id = task.parent_task_id
        chapter = db.query(Chapter).filter(Chapter.id == task.chapter_id, Chapter.novel_id == task.novel_id).first()
        novel = db.get(Novel, task.novel_id)
        if not novel or not chapter:
            raise ValueError("小说或章回已不存在")
        if not (chapter.content or "").strip():
            raise ValueError("章回内容为空")

        task.status = "running"
        task.started_at = datetime.utcnow()
        task.progress = 10
        task.current_step = "正在 AI 拆分章回"
        db.commit()
        result = await NovelService(db).split_chapter(
            novel=novel, chapter=chapter,
            character_names=CharacterRepository(db).get_names_by_novel(novel.id),
            scene_names=SceneRepository(db).get_names_by_novel(novel.id),
            prop_names=PropRepository(db).get_visual_names_by_novel(novel.id),
        )
        db.refresh(task)
        if task.status == "cancelled":
            return
        if not result.get("success") or not (result.get("data") or {}).get("shots"):
            raise ValueError(result.get("message") or (result.get("data") or {}).get("error") or "AI 拆分失败或未生成分镜")
        task.status = "completed"
        task.progress = 100
        task.current_step = "AI 拆分完成"
        task.completed_at = datetime.utcnow()
        db.commit()
    except asyncio.CancelledError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        task = db.get(Task, task_id)
        if task and task.status not in TERMINAL_STATUSES:
            parent_id = task.parent_task_id
            task.status = "failed"
            task.error_message = str(exc)
            task.current_step = "AI 拆分失败"
            task.completed_at = datetime.utcnow()
            db.commit()
    finally:
        try:
            if parent_id:
                refresh_split_batch(db, parent_id)
        finally:
            db.close()
