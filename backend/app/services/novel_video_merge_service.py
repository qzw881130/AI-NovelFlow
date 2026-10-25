"""Novel-level chapter video merge tasks."""
import asyncio
import json
import os
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from app.core.database import SessionLocal
from app.models.novel import Chapter
from app.models.task import Task
from app.repositories.chapter_repository import ChapterRepository
from app.services.background_workers import persistent_job, worker_manager


def enqueue_novel_video_merge_task(task_id: str) -> None:
    payload = {"task_id": task_id}
    worker_manager.worker("novel_video").enqueue(persistent_job(
        task_id,
        "app.services.novel_video_merge_service:run_novel_video_merge_task",
        payload,
        lambda: run_novel_video_merge_task(**payload),
    ))
from app.services.file_storage import file_storage
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.utils.time_utils import format_datetime


_merge_locks: dict[str, asyncio.Lock] = {}


def _mix_chapter_background_music(video_path: str, music_path: str, output_path: str) -> None:
    """Copy the chapter picture and mix its original audio with a quiet music bed."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=index", "-of", "csv=p=0", video_path],
        capture_output=True, text=True, timeout=45)
    if probe.returncode:
        raise RuntimeError(f"无法检查章回视频音轨：{probe.stderr[-300:]}")
    has_original_audio = bool(probe.stdout.strip())
    music_filter = "[1:a:0]aresample=48000,aformat=channel_layouts=stereo,volume=-23dB[music]"
    filter_graph = ("[0:a:0]aresample=48000,aformat=channel_layouts=stereo[base];"
        + music_filter + ";[base][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.95:attack=5:release=50:level=0[out]") if has_original_audio else music_filter.replace("[music]", "[out]")
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror",
        "-i", video_path, "-i", music_path, "-filter_complex", filter_graph,
        "-map", "0:v:0", "-map", "[out]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-y", output_path]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    if result.returncode:
        raise RuntimeError(f"章回背景音乐混音失败：{result.stderr[-500:]}")


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
        enqueue_novel_video_merge_task(task_id)
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
        "withBackgroundMusic": bool(metadata.get("background_music_chapter_count")),
        "backgroundMusicChapterCount": metadata.get("background_music_chapter_count") or 0,
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
            if metadata.get("include_background_music") and snapshot.get("backgroundMusicUrl"):
                music_path = url_to_local_path(snapshot["backgroundMusicUrl"])
                if not music_path or not Path(music_path).is_file():
                    raise RuntimeError(f"第 {chapter.number} 章的背景音乐文件已丢失")
                segments[-1]["background_music_path"] = music_path

        if len(segments) < 2:
            raise RuntimeError("至少需要选择两个章回视频")

        task.progress = 20
        task.current_step = f"已找到 {len(segments)} 个章回视频，正在计算缓存签名..."
        db.commit()

        signature_inputs = []
        for segment in segments:
            signature_inputs.append({key: segment[key] for key in ("kind", "key", "path")})
            if segment.get("background_music_path"):
                signature_inputs.append({"kind": "background_music", "key": segment["key"], "path": segment["background_music_path"]})
        signature = await asyncio.to_thread(
            file_storage.get_video_merge_signature,
            f"novel_chapters:{video_variant}:{target_megapixels}" + (":bgm-v1" if any(segment.get("background_music_path") for segment in segments) else ""),
            signature_inputs,
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
                    with tempfile.TemporaryDirectory(prefix="novelflow_bgm_merge_") as temporary_dir:
                        video_paths = []
                        for index, segment in enumerate(segments):
                            if segment.get("background_music_path"):
                                mixed = str(Path(temporary_dir) / f"chapter-{index:03d}.mp4")
                                await asyncio.to_thread(_mix_chapter_background_music,
                                    segment["path"], segment["background_music_path"], mixed)
                                video_paths.append(mixed)
                            else:
                                video_paths.append(segment["path"])
                        result = await file_storage.merge_videos(video_paths, str(temp_path))
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
            "background_music_chapter_count": sum(bool(segment.get("background_music_path")) for segment in segments),
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
