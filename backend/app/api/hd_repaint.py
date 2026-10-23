import copy
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.schemas.shot import BatchHdRepaintRequest, HdRepaintRequest
from app.services.hd_repaint_service import (
    ALLOWED_HD_MEGAPIXELS,
    build_hd_repaint_snapshot,
    enqueue_hd_repaint_batch,
    enqueue_hd_repaint_task,
    resolve_source_video_task,
)


router = APIRouter()


def _create_hd_task(db: Session, novel: Novel, chapter: Chapter, shot: Shot, target_mp: float, source_task_id: str | None = None, parent_id: str | None = None, order: int | None = None) -> Task:
    active_tasks = db.query(Task).filter(
        Task.type == "shot_video_hd",
        Task.shot_id == shot.id,
        Task.status.in_(["pending", "running"]),
    ).all()
    from app.services.hd_repaint_service import hd_task_megapixels
    if any(hd_task_megapixels(task) == float(target_mp) for task in active_tasks):
        raise ValueError(f"镜{shot.index} 的 {target_mp} MP 高清重绘已在队列中")
    source = resolve_source_video_task(db, shot, source_task_id)
    metadata, clips = build_hd_repaint_snapshot(db, shot, source, target_mp)
    task = Task(
        type="shot_video_hd",
        status="pending",
        name=f"高清重绘: 镜{shot.index}",
        description=f"Replay 章节 '{chapter.title}' 镜{shot.index} 的成功视频 Execution，仅覆盖 Megapixels 为 {target_mp}",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        source_task_id=source.id,
        parent_task_id=parent_id,
        batch_order=order,
        workflow_id=metadata.get("workflow_id"),
        workflow_json=json.dumps(metadata.get("source_workflow_json"), ensure_ascii=False) if metadata.get("source_workflow_json") else None,
        prompt_text=source.prompt_text,
        reference_images=source.reference_images,
        video_director_clips=json.dumps(clips, ensure_ascii=False) if clips else None,
        seed=metadata.get("source_seed"),
        metadata_json=json.dumps(metadata, ensure_ascii=False),
        current_step="等待高清 Replay",
    )
    db.add(task)
    db.flush()
    shot.hd_video_status = "pending"
    shot.hd_video_task_id = task.id
    return task


def _format_batch(db: Session, batch: Task) -> dict:
    children = db.query(Task).filter(Task.parent_task_id == batch.id, Task.type == "shot_video_hd").all()
    counts = {status: len([task for task in children if task.status == status]) for status in ["pending", "running", "completed", "failed", "cancelled"]}
    metadata = json.loads(batch.metadata_json or "{}")
    return {
        "id": batch.id,
        "status": batch.status,
        "progress": batch.progress or 0,
        "currentStep": batch.current_step,
        "targetMegapixels": metadata.get("target_megapixels"),
        "total": len(children),
        **counts,
    }


@router.get("/{novel_id}/chapters/{chapter_id}/hd-repaints/latest", response_model=dict)
async def get_latest_hd_batch(novel_id: str, chapter_id: str, target_megapixels: float | None = Query(None), db: Session = Depends(get_db)):
    batches = db.query(Task).filter(
        Task.type == "shot_video_hd_batch",
        Task.novel_id == novel_id,
        Task.chapter_id == chapter_id,
    ).order_by(Task.created_at.desc()).all()
    batch = next((item for item in batches if target_megapixels is None or float(json.loads(item.metadata_json or "{}").get("target_megapixels") or 0) == float(target_megapixels)), None)
    return {"success": True, "data": _format_batch(db, batch) if batch else None}


@router.get("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/hd-repaint/source", response_model=dict)
async def get_hd_repaint_source(novel_id: str, chapter_id: str, shot_id: str, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.chapter_id == chapter_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    try:
        source = resolve_source_video_task(db, shot)
        metadata, clips = build_hd_repaint_snapshot(db, shot, source, 1.0)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "success": True,
        "data": {
            "sourceTaskId": source.id,
            "sourceVideoUrl": metadata.get("source_video_url") or shot.video_url,
            "seed": metadata.get("source_seed") or source.seed,
            "sourceMegapixels": metadata.get("source_megapixels"),
            "duration": shot.duration,
            "referenceImages": json.loads(source.reference_images or "[]"),
            "isMultiClip": bool(clips),
            "clipCount": len(clips) or 1,
            "clips": [{
                "windowIndex": clip.get("window_index"),
                "seed": clip.get("source_seed"),
                "sourceMegapixels": clip.get("source_megapixels"),
            } for clip in clips],
            "hdVideoUrl": shot.hd_video_url,
            "hdVideoStatus": shot.hd_video_status,
            "hdMegapixels": float(shot.hd_video_megapixels) if shot.hd_video_megapixels else None,
        },
    }


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/hd-repaint", response_model=dict)
async def create_hd_repaint(novel_id: str, chapter_id: str, shot_id: str, request: HdRepaintRequest, db: Session = Depends(get_db)):
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first()
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.chapter_id == chapter_id).first()
    if not novel or not chapter or not shot:
        raise HTTPException(status_code=404, detail="小说、章节或分镜不存在")
    try:
        task = _create_hd_task(db, novel, chapter, shot, request.target_megapixels, request.source_task_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    enqueue_hd_repaint_task(task.id)
    return {"success": True, "message": "高清重绘任务已创建", "data": {"taskId": task.id, "status": task.status}}


@router.post("/{novel_id}/chapters/{chapter_id}/hd-repaints/batch", response_model=dict)
async def create_hd_repaint_batch(novel_id: str, chapter_id: str, request: BatchHdRepaintRequest, db: Session = Depends(get_db)):
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first()
    if not novel or not chapter:
        raise HTTPException(status_code=404, detail="小说或章节不存在")
    shot_ids = list(dict.fromkeys(request.shot_ids))
    if not shot_ids:
        raise HTTPException(status_code=400, detail="请选择分镜")
    shots = db.query(Shot).filter(Shot.chapter_id == chapter_id, Shot.id.in_(shot_ids)).all()
    by_id = {shot.id: shot for shot in shots}
    if len(by_id) != len(shot_ids):
        raise HTTPException(status_code=404, detail="部分分镜不存在")
    batch = Task(
        type="shot_video_hd_batch",
        status="pending",
        name="批量高清重绘",
        description=f"为章节 '{chapter.title}' 批量高清重绘 {len(shot_ids)} 个分镜，目标 {request.target_megapixels} MP",
        novel_id=novel_id,
        chapter_id=chapter_id,
        metadata_json=json.dumps({"target_megapixels": request.target_megapixels, "shot_ids": shot_ids}, ensure_ascii=False),
        current_step="等待处理",
    )
    db.add(batch)
    db.flush()
    children = []
    try:
        for order, shot_id in enumerate(shot_ids, 1):
            children.append(_create_hd_task(db, novel, chapter, by_id[shot_id], request.target_megapixels, parent_id=batch.id, order=order))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    for child in children:
        enqueue_hd_repaint_task(child.id)
    enqueue_hd_repaint_batch(batch.id)
    return {
        "success": True,
        "message": f"已创建 {len(children)} 个持久化高清重绘任务",
        "data": {
            "batchTaskId": batch.id,
            "tasks": [{"taskId": child.id, "shotId": child.shot_id, "status": child.status} for child in children],
        },
    }


@router.post("/{novel_id}/chapters/{chapter_id}/hd-repaints/{batch_id}/retry-failed", response_model=dict)
async def retry_failed_hd_repaints(novel_id: str, chapter_id: str, batch_id: str, db: Session = Depends(get_db)):
    batch = db.query(Task).filter(Task.id == batch_id, Task.type == "shot_video_hd_batch", Task.chapter_id == chapter_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批量任务不存在")
    failed = db.query(Task).filter(Task.parent_task_id == batch.id, Task.type == "shot_video_hd", Task.status == "failed").all()
    if not failed:
        return {"success": True, "message": "没有失败项需要重试"}
    from app.services.hd_repaint_service import clone_hd_task_for_retry
    source_metadata = json.loads(batch.metadata_json or "{}")
    source_metadata["retry_of_batch_task_id"] = batch.id
    retry_batch = Task(
        type="shot_video_hd_batch",
        status="pending",
        name=batch.name,
        description=batch.description,
        novel_id=novel_id,
        chapter_id=chapter_id,
        metadata_json=json.dumps(source_metadata, ensure_ascii=False),
        current_step="等待处理",
    )
    db.add(retry_batch)
    db.flush()
    retries = []
    for order, source in enumerate(failed, 1):
        retry = clone_hd_task_for_retry(db, source, retry_batch.id, order)
        retries.append(retry)
        shot = db.query(Shot).filter(Shot.id == source.shot_id).first()
        if shot:
            shot.hd_video_status = "pending"
            shot.hd_video_task_id = retry.id
    db.commit()
    for task in retries:
        enqueue_hd_repaint_task(task.id)
    enqueue_hd_repaint_batch(retry_batch.id)
    return {"success": True, "message": f"已创建新批次并重新提交 {len(retries)} 个失败项", "data": {"batchTaskId": retry_batch.id}}
