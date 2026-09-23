"""Novel-level chapter video merge tasks."""
import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from app.core.database import SessionLocal
from app.models.novel import Chapter
from app.models.task import Task
from app.repositories.chapter_repository import ChapterRepository
from app.services.background_workers import worker_manager
from app.services.file_storage import file_storage
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.utils.time_utils import format_datetime


_merge_locks: dict[str, asyncio.Lock] = {}


def resume_active_novel_video_merges() -> int:
    """Requeue novel video merges lost during a backend restart."""
    db = SessionLocal()
    try:
        tasks = db.query(Task).filter(
            Task.type == "novel_video",
            Task.status.in_(["pending", "running"]),
        ).order_by(Task.created_at).all()
        for task in tasks:
            task.status = "pending"
            task.current_step = "服务重启，等待恢复合并..."
        db.commit()
        task_ids = [task.id for task in tasks]
    finally:
        db.close()

    for task_id in task_ids:
        worker_manager.worker("novel_video").enqueue(lambda task_id=task_id: run_novel_video_merge_task(task_id))
    return len(task_ids)


def format_novel_video_merge(task: Task) -> dict:
    try:
        metadata = json.loads(task.metadata_json or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    return {
        "id": task.id,
        "status": task.status,
        "progress": task.progress or 0,
        "currentStep": task.current_step,
        "errorMessage": task.error_message,
        "videoUrl": task.result_url or metadata.get("video_url"),
        "fileSize": metadata.get("file_size"),
        "duration": metadata.get("duration"),
        "cacheHit": bool(metadata.get("cache_hit")),
        "chapters": metadata.get("chapters") or [],
        "videoVariant": metadata.get("video_variant") or "draft",
        "targetMegapixels": metadata.get("target_megapixels"),
        "createdAt": format_datetime(task.created_at),
        "completedAt": format_datetime(task.completed_at),
    }


async def run_novel_video_merge_task(task_id: str) -> None:
    db = SessionLocal()
    task = None
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or task.status not in {"pending", "running"}:
            return

        task.status = "running"
        task.progress = 5
        task.current_step = "正在准备章回视频..."
        task.started_at = datetime.utcnow()
        db.commit()

        try:
            metadata = json.loads(task.metadata_json or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        chapter_ids = list(dict.fromkeys(metadata.get("chapter_ids") or []))
        video_variant = metadata.get("video_variant") or "draft"
        target_megapixels = metadata.get("target_megapixels")
        chapters = db.query(Chapter).filter(
            Chapter.novel_id == task.novel_id,
            Chapter.id.in_(chapter_ids),
        ).order_by(Chapter.number).all()
        if len(chapters) != len(chapter_ids):
            raise RuntimeError("选择的章回不存在或不属于当前小说")

        segments = []
        chapter_snapshot = metadata.get("chapters") if isinstance(metadata.get("chapters"), list) else []
        snapshot_by_id = {item.get("id"): item for item in chapter_snapshot}
        chapter_repo = ChapterRepository(db)
        for chapter in chapters:
            snapshot = snapshot_by_id.get(chapter.id) or {}
            video_url = snapshot.get("videoUrl")
            if not video_url:
                legacy_info = chapter_repo.get_final_chapter_video_info(chapter, video_variant, target_megapixels)
                video_url = (legacy_info or {}).get("hdChapterVideoUrl" if video_variant == "hd" else "chapterVideoUrl")
            video_path = url_to_local_path(video_url) if video_url else None
            if not video_path or not Path(video_path).is_file():
                raise RuntimeError(f"第 {chapter.number} 章《{chapter.title}》没有可用的章回视频")
            segments.append({"kind": "chapter", "key": chapter.id, "path": video_path})

        if len(segments) < 2:
            raise RuntimeError("至少需要选择两个章回视频")

        task.progress = 20
        task.current_step = f"已找到 {len(segments)} 个章回视频，正在计算缓存签名..."
        db.commit()

        signature = await asyncio.to_thread(
            file_storage.get_video_merge_signature,
            f"novel_chapters:{video_variant}:{target_megapixels}",
            segments,
        )
        output_dir = file_storage._get_story_dir(task.novel_id) / ("novel-hd-merged-videos" if video_variant == "hd" else "novel-merged-videos")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"novel-{signature}.mp4"
        lock = _merge_locks.setdefault(str(output_path), asyncio.Lock())

        async with lock:
            if output_path.is_file() and output_path.stat().st_size > 0:
                cache_hit = True
            else:
                cache_hit = False
                task.progress = 35
                task.current_step = f"正在合并 {len(segments)} 个章回视频..."
                db.commit()
                temp_path = output_dir / f".novel-{uuid.uuid4().hex}.tmp.mp4"
                try:
                    result = await file_storage.merge_videos(
                        [segment["path"] for segment in segments],
                        str(temp_path),
                    )
                    if not result.get("success"):
                        raise RuntimeError(result.get("message") or "章回视频合并失败")
                    os.replace(temp_path, output_path)
                finally:
                    if temp_path.exists():
                        temp_path.unlink()

        video_url = local_path_to_url(str(output_path))
        if not video_url:
            raise RuntimeError("无法生成合并视频访问地址")
        metadata.update({
            "chapter_ids": [chapter.id for chapter in chapters],
            "chapters": chapter_snapshot,
            "video_variant": video_variant,
            "target_megapixels": target_megapixels,
            "signature": signature,
            "cache_hit": cache_hit,
            "video_url": video_url,
            "file_size": output_path.stat().st_size,
            "duration": chapter_repo._probe_video_duration(str(output_path)),
        })
        task.status = "completed"
        task.progress = 100
        task.current_step = "合并完成（使用缓存）" if cache_hit else "合并完成"
        task.result_url = video_url
        task.error_message = None
        task.completed_at = datetime.utcnow()
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()
    except Exception as exc:
        print(f"[NovelVideoMergeTask {task_id}] Error: {exc}")
        if task:
            task.status = "failed"
            task.current_step = "合并失败"
            task.error_message = str(exc)
            task.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
