"""Queue reviewed subtitle renders without replacing the current video on failure."""

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.novel import Chapter
from app.models.task import Task
from app.services.background_workers import persistent_job, worker_manager
from app.services.chapter_subtitles import _duration, burn_subtitles, english_cues, file_url, read_cues, translate_cues, validate_cues, write_cues, write_srt
from app.utils.path_utils import url_to_local_path


def format_subtitle_render(task: Task | None) -> dict | None:
    if task is None:
        return None
    return {
        "id": task.id, "status": task.status, "progress": task.progress or 0,
        "currentStep": task.current_step, "errorMessage": task.error_message,
        "videoUrl": task.result_url,
    }


def latest_subtitle_renders(db: Session, parent_ids: list[str]) -> dict[str, Task]:
    if not parent_ids:
        return {}
    tasks = db.query(Task).filter(
        Task.type == "subtitle_render", Task.parent_task_id.in_(parent_ids),
    ).order_by(Task.created_at.desc(), Task.id.desc()).all()
    result = {}
    for task in tasks:
        result.setdefault(task.parent_task_id, task)
    return result


async def queue_subtitle_render(db: Session, parent: Task, raw_cues: list[dict]) -> Task:
    """Validate and persist a draft, then enqueue one durable render task."""
    active = db.query(Task.id).filter(
        Task.type == "subtitle_render", Task.parent_task_id == parent.id,
        Task.status.in_(["pending", "running"]),
    ).first()
    if active:
        raise ValueError("该视频已有字幕更新任务，请等待完成后再保存")
    metadata = json.loads(parent.metadata_json or "{}")
    subtitle = metadata.get("subtitle")
    if not isinstance(subtitle, dict) or not subtitle.get("source_url"):
        raise FileNotFoundError("该任务没有字幕")
    source_local = url_to_local_path(subtitle["source_url"])
    source = Path(source_local) if source_local else None
    if not source or not source.is_file():
        raise FileNotFoundError("字幕对应的原视频不存在")
    if not subtitle.get("srt_url") or not url_to_local_path(subtitle["srt_url"]):
        raise FileNotFoundError("当前 SRT 文件不存在")
    if subtitle.get("cues_url") and not url_to_local_path(subtitle["cues_url"]):
        raise FileNotFoundError("字幕时间轴文件不存在")
    cues = validate_cues(raw_cues, await asyncio.to_thread(_duration, source))
    if not cues:
        raise ValueError("字幕不能为空")
    if (subtitle.get("mode") or metadata.get("subtitle_mode")) == "bilingual":
        previous = read_cues(subtitle)
        for cue, old in zip(cues, previous):
            if cue["text"] != old.get("text") and cue.get("en_text") == old.get("en_text"):
                cue.pop("en_text", None)

    render_id = str(uuid.uuid4())
    draft_dir = source.parent / "subtitle-edits"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft = draft_dir / f"{render_id}.json"
    await asyncio.to_thread(write_cues, cues, draft)
    task = Task(
        id=render_id, type="subtitle_render", status="pending",
        novel_id=parent.novel_id, chapter_id=parent.chapter_id,
        parent_task_id=parent.id, name=f"更新视频字幕: {parent.name}",
        progress=0, current_step="等待字幕烧录队列",
        created_at=datetime.utcnow(),
        metadata_json=json.dumps({"draft_path": str(draft), "source_url": subtitle["source_url"]}, ensure_ascii=False),
    )
    try:
        db.add(task)
        db.commit()
        payload = {"task_id": render_id}
        worker_manager.worker("subtitle_render").enqueue(persistent_job(
            render_id, "app.services.subtitle_render_service:run_subtitle_render_task",
            payload, lambda: run_subtitle_render_task(**payload),
        ))
    except Exception:
        db.rollback()
        draft.unlink(missing_ok=True)
        task.status = "failed"
        task.error_message = "字幕任务入队失败"
        db.add(task)
        db.commit()
        raise
    return task


async def run_subtitle_render_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id, Task.type == "subtitle_render").first()
        if not task or task.status not in {"pending", "running"}:
            return
        parent = db.query(Task).filter(
            Task.id == task.parent_task_id, Task.status == "completed",
            Task.type.in_(["novel_video", "chapter_video"]),
        ).first()
        if not parent:
            raise ValueError("原合并视频任务不可用")
        render_meta = json.loads(task.metadata_json or "{}")
        parent_meta = json.loads(parent.metadata_json or "{}")
        subtitle = parent_meta.get("subtitle") or {}
        if subtitle.get("source_url") != render_meta.get("source_url"):
            raise ValueError("原视频已变更，请刷新字幕后重试")
        source_local = url_to_local_path(render_meta["source_url"])
        source = Path(source_local) if source_local else None
        draft = Path(render_meta["draft_path"])
        if not source or not source.is_file() or not draft.is_file():
            raise FileNotFoundError("字幕原视频或待处理字幕不存在")
        cues = validate_cues(json.loads(draft.read_text(encoding="utf-8")),
                             await asyncio.to_thread(_duration, source))
        if not cues:
            raise ValueError("字幕不能为空")

        subtitle_mode = subtitle.get("mode") or parent_meta.get("subtitle_mode") or "zh"
        if subtitle_mode == "bilingual":
            task.status = "running"
            task.started_at = datetime.utcnow()
            task.progress = 10
            task.current_step = "翻译更新的英文字幕"
            db.commit()
            cues = await translate_cues(db, cues, parent.novel_id, parent.chapter_id or "")

        task.status = "running"
        task.started_at = task.started_at or datetime.utcnow()
        task.progress = 15
        task.current_step = "烧录校对后的字幕视频"
        db.commit()
        burned = await asyncio.to_thread(burn_subtitles, source, cues, source.parent)
        burned_url = file_url(burned)
        preview_url = parent_meta.get("nameplate_preview_url")
        if parent.type == "chapter_video" and parent_meta.get("nameplate_status") == "pending_confirmation" and subtitle.get("preview_source_url"):
            preview_local = url_to_local_path(subtitle["preview_source_url"])
            preview_source = Path(preview_local) if preview_local else None
            if not preview_source or not preview_source.is_file():
                raise FileNotFoundError("姓名牌预览原视频不存在")
            task.progress = 65
            task.current_step = "更新姓名牌预览字幕"
            db.commit()
            preview = await asyncio.to_thread(burn_subtitles, preview_source, cues, source.parent)
            preview_url = file_url(preview)

        db.refresh(task, attribute_names=["status"])
        if task.status == "cancelled":
            return
        db.refresh(parent, attribute_names=["metadata_json", "result_url"])
        parent_meta = json.loads(parent.metadata_json or "{}")
        subtitle = parent_meta.get("subtitle") or {}
        if subtitle.get("source_url") != render_meta["source_url"]:
            raise ValueError("原视频已变更，请刷新字幕后重试")
        task.progress = 85
        task.current_step = "保存 SRT 和视频结果"
        db.commit()
        # New versioned sidecars keep the published files intact if rendering fails.
        sidecar_dir = source.parent / "subtitle-edits"
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        srt_path = sidecar_dir / f"{task_id}.srt"
        cues_path = sidecar_dir / f"{task_id}-cues.json"
        await asyncio.to_thread(write_srt, cues, srt_path)
        en_srt_url = None
        if subtitle_mode == "bilingual":
            en_srt_path = sidecar_dir / f"{task_id}-en.srt"
            await asyncio.to_thread(write_srt, english_cues(cues), en_srt_path)
            en_srt_url = file_url(en_srt_path)
        await asyncio.to_thread(write_cues, cues, cues_path)
        old_url = parent_meta.get("video_url")
        subtitle.update({
            "count": len(cues), "srt_url": file_url(srt_path),
            "cues_url": file_url(cues_path), "burned_url": burned_url,
            "status": "reviewed",
        })
        if subtitle_mode == "bilingual":
            subtitle["en_srt_url"] = en_srt_url
        subtitle.pop("cues", None)
        parent_meta.update({
            "subtitle": subtitle, "video_url": burned_url,
            "file_size": burned.stat().st_size,
        })
        if parent.type == "chapter_video":
            parent_meta["nameplate_preview_url"] = preview_url
            chapter = db.query(Chapter).filter(
                Chapter.id == parent.chapter_id, Chapter.novel_id == parent.novel_id,
            ).first()
            if chapter and parent_meta.get("is_final_video"):
                if parent_meta.get("video_variant") == "hd" and chapter.hd_final_video == old_url:
                    chapter.hd_final_video = burned_url
                elif parent_meta.get("video_variant") != "hd" and chapter.final_video == old_url:
                    chapter.final_video = burned_url
        parent.result_url = burned_url
        parent.metadata_json = json.dumps(parent_meta, ensure_ascii=False)
        task.result_url = burned_url
        task.status = "completed"
        task.progress = 100
        task.current_step = "字幕视频已更新"
        task.completed_at = datetime.utcnow()
        db.commit()
        try:
            draft.unlink(missing_ok=True)
        except OSError:
            pass
    finally:
        db.close()
