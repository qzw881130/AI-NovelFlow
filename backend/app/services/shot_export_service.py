"""Durable Shot exports: HTTP submits/polls; a serial worker builds on disk."""
import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime

from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.services.background_workers import persistent_job, worker_manager
from app.services.file_storage import file_storage
from app.services.shot_export_selection import SHOT_EXPORT_SECTIONS


def export_file(task):
    return (file_storage.base_dir / f"story_{task.novel_id[:8]}" /
            f"chapter_{task.chapter_id[:8]}" / "exports" / f"{task.id}.zip")


def get_export(db, novel_id, chapter_id, shot_id, task_id):
    task = db.query(Task).filter(Task.id == task_id, Task.type == "shot_export",
        Task.novel_id == novel_id, Task.chapter_id == chapter_id, Task.shot_id == shot_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    return task


def export_status(task):
    return {"task_id": task.id, "status": task.status, "progress": task.progress,
            "current_step": task.current_step, "error_message": task.error_message,
            "download_url": task.result_url if task.status == "completed" else None}


def create_export(db, novel_id, chapter_id, shot_id, include):
    selected = set(SHOT_EXPORT_SECTIONS if include is None else include)
    if not selected or not selected <= SHOT_EXPORT_SECTIONS:
        raise HTTPException(status_code=400, detail="请选择有效的导出项")
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first()
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.chapter_id == chapter_id).first()
    if not novel or not chapter or not shot:
        raise HTTPException(status_code=404, detail="小说、章节或分镜不存在")
    signature = hashlib.sha256(json.dumps([sorted(selected), shot.video_director_plan,
        shot.image_url, shot.video_url, shot.updated_at.isoformat() if shot.updated_at else None],
        ensure_ascii=False).encode()).hexdigest()
    # Retrying a lost submit/poll response must not start a second expensive export.
    for active in db.query(Task).filter(Task.type == "shot_export", Task.shot_id == shot_id,
            Task.status.in_(["pending", "running"])).all():
        if json.loads(active.metadata_json or "{}").get("signature") == signature:
            return export_status(active)
    task = Task(type="shot_export", name=f"导出 Shot {shot.index} 生产包", status="pending",
        novel_id=novel_id, chapter_id=chapter_id, shot_id=shot_id,
        current_step="等待后台打包", metadata_json=json.dumps({"sections": sorted(selected), "signature": signature}))
    db.add(task)
    db.commit()
    db.refresh(task)
    payload = {"task_id": task.id}
    try:
        worker_manager.worker("shot_export").enqueue(persistent_job(
            task.id, "app.services.shot_export_service:run_export_task", payload,
            lambda: run_export_task(task.id)))
    except Exception:
        task.status = "failed"
        task.error_message = "导出任务入队失败，请重试"
        task.completed_at = datetime.utcnow()
        db.commit()
        raise
    return export_status(task)


async def run_export_task(task_id):
    # Own DB session inside the thread; never share the request session or block
    # the async worker/event loop with ffprobe, hashing or ZIP file writes.
    await asyncio.to_thread(_build_export, task_id)


def _build_export(task_id):
    from app.api.shots import write_shot_video_materials_package
    db = SessionLocal()
    partial = None
    attempt = uuid.uuid4().hex
    try:
        task = db.query(Task).filter(Task.id == task_id, Task.type == "shot_export").first()
        if not task or task.status not in {"pending", "running"}:
            return
        task.status = "running"
        task.progress = 5
        task.started_at = datetime.utcnow()
        task.current_step = "校验素材并打包中"
        metadata = json.loads(task.metadata_json)
        metadata["attempt"] = attempt
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()
        novel = db.query(Novel).filter(Novel.id == task.novel_id).first()
        chapter = db.query(Chapter).filter(Chapter.id == task.chapter_id, Chapter.novel_id == task.novel_id).first()
        shot = db.query(Shot).filter(Shot.id == task.shot_id, Shot.chapter_id == task.chapter_id).first()
        if not novel or not chapter or not shot:
            raise ValueError("小说、章节或分镜已不存在")
        path = export_file(task)
        path.parent.mkdir(parents=True, exist_ok=True)
        for abandoned in path.parent.glob(f"{task.id}.*.zip.part"):
            abandoned.unlink(missing_ok=True)
        partial = path.with_suffix(f".{attempt}.zip.part")
        def progress(done, total):
            db.refresh(task, attribute_names=["status", "metadata_json"])
            if task.status != "running" or json.loads(task.metadata_json).get("attempt") != attempt:
                raise ExportStopped()
            task.progress = 5 + int(85 * done / max(total, 1))
            task.current_step = f"校验并打包 Clip {min(done + 1, total)}/{total}" if total else "整理导出清单"
            db.commit()
        filename = write_shot_video_materials_package(db, novel, chapter, shot, set(metadata["sections"]), partial, progress)
        db.refresh(task, attribute_names=["status", "metadata_json"])
        if task.status != "running" or json.loads(task.metadata_json).get("attempt") != attempt:
            return
        os.replace(partial, path)
        metadata["filename"] = filename
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        task.result_url = f"/api/novels/{task.novel_id}/chapters/{task.chapter_id}/shots/{task.shot_id}/exports/{task.id}/download"
        task.status = "completed"
        task.progress = 100
        task.current_step = "生产包已就绪"
        task.error_message = None
        task.completed_at = datetime.utcnow()
        db.commit()
    except ExportStopped:
        return
    except Exception as exc:
        db.rollback()
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or task.status not in {"pending", "running"} or json.loads(task.metadata_json).get("attempt") != attempt:
            return
        if task:
            task.status = "failed"
            task.error_message = str(getattr(exc, "detail", None) or exc)
            task.current_step = "打包失败"
            task.completed_at = datetime.utcnow()
            db.commit()
        raise
    finally:
        if partial:
            partial.unlink(missing_ok=True)
        db.close()


class ExportStopped(Exception):
    """A cancelled/replaced worker may not publish or fail another attempt."""
