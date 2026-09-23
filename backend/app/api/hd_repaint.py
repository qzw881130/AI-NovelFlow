import copy
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.schemas.shot import BatchHdRepaintRequest, HdRepaintRequest, SetCurrentVideoVariantRequest
from app.services.hd_repaint_service import (
    ALLOWED_HD_MEGAPIXELS,
    build_hd_repaint_snapshot,
    enqueue_hd_repaint_batch,
    enqueue_hd_repaint_task,
    resolve_source_video_task,
)


router = APIRouter()


def _create_hd_task(db: Session, novel: Novel, chapter: Chapter, shot: Shot, target_mp: float, source_task_id: str | None = None, parent_id: str | None = None, order: int | None = None) -> Task:
    active = db.query(Task).filter(
        Task.type == "shot_video_hd",
        Task.shot_id == shot.id,
        Task.status.in_(["pending", "running"]),
    ).first()
    if active:
        raise ValueError(f"镜{shot.index} 已有高清重绘任务")
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
async def get_latest_hd_batch(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    batch = db.query(Task).filter(
        Task.type == "shot_video_hd_batch",
        Task.novel_id == novel_id,
        Task.chapter_id == chapter_id,
    ).order_by(Task.created_at.desc()).first()
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
            "currentVideoVariant": shot.current_video_variant or "draft",
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
    for task in failed:
        task.status = "pending"
        task.progress = 0
        task.error_message = None
        task.completed_at = None
        task.comfyui_prompt_id = None
        task.result_url = None
        metadata = json.loads(task.metadata_json or "{}")
        task.workflow_json = json.dumps(metadata.get("source_workflow_json"), ensure_ascii=False) if metadata.get("source_workflow_json") else None
        clips = json.loads(task.video_director_clips or "[]")
        for clip in clips:
            for key in ["replay_workflow_json", "repaint_prompt_id", "video_url", "local_path", "source_video_url", "generated_at", "seed"]:
                clip.pop(key, None)
            clip["status"] = "PENDING"
        task.video_director_clips = json.dumps(clips, ensure_ascii=False) if clips else None
        shot = db.query(Shot).filter(Shot.id == task.shot_id).first()
        if shot:
            shot.hd_video_status = "pending"
    batch.status = "pending"
    batch.completed_at = None
    batch.error_message = None
    db.commit()
    for task in failed:
        enqueue_hd_repaint_task(task.id)
    enqueue_hd_repaint_batch(batch.id)
    return {"success": True, "message": f"已重新提交 {len(failed)} 个失败项"}


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/current-video", response_model=dict)
async def set_current_video_variant(novel_id: str, chapter_id: str, shot_id: str, request: SetCurrentVideoVariantRequest, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.chapter_id == chapter_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    if request.variant == "hd" and not shot.hd_video_url:
        raise HTTPException(status_code=400, detail="该分镜尚无高清视频")
    if request.variant == "draft" and not shot.video_url:
        raise HTTPException(status_code=400, detail="该分镜尚无初稿视频")
    shot.current_video_variant = request.variant
    db.commit()
    return {"success": True, "data": {"currentVideoVariant": shot.current_video_variant}}


@router.post("/{novel_id}/chapters/{chapter_id}/current-video/hd-all", response_model=dict)
async def set_all_hd_current(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    shots = db.query(Shot).filter(Shot.chapter_id == chapter_id).order_by(Shot.index).all()
    missing = [shot.index for shot in shots if not shot.hd_video_url]
    if missing:
        raise HTTPException(status_code=400, detail=f"以下分镜缺少高清视频：{', '.join(map(str, missing))}")
    for shot in shots:
        shot.current_video_variant = "hd"
    db.commit()
    return {"success": True, "data": {"updated": len(shots)}}
