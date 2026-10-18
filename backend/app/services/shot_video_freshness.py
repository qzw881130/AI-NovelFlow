"""Compare the currently selected main image with the currently selected Shot video."""

import json
import os
from datetime import datetime, timezone

from app.models.task import Task
from app.utils.path_utils import url_to_local_path


def _timestamp(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _file_timestamp(url, fallback_path=None):
    path = url_to_local_path(url) if url else None
    if not path and fallback_path and os.path.isfile(fallback_path):
        path = fallback_path
    try:
        return os.path.getmtime(path) if path else None
    except OSError:
        return None


def _task_timestamp(db, task_id, current_url):
    if not task_id or not current_url:
        return None
    task = db.get(Task, task_id)
    if task and task.status == "completed" and task.result_url == current_url:
        return _timestamp(task.completed_at)
    return None


def _last_completed_shot_video_time(db, shot_id):
    """An invalidated assembly has no current URL, but its completed task remains."""
    tasks = db.query(Task).filter(
        Task.shot_id == shot_id,
        Task.type == "shot_video",
        Task.status == "completed",
        Task.completed_at.isnot(None),
    ).order_by(Task.completed_at.desc()).all()
    for task in tasks:
        try:
            metadata = json.loads(task.metadata_json or "{}")
        except (TypeError, ValueError):
            metadata = {}
        if metadata.get("batch_shot_child") and metadata.get("batch_state") == "COMPLETED":
            return _timestamp(task.completed_at)
        if task.result_url and not metadata.get("batch_shot_child") and metadata.get("execution_scope") != "CLIP":
            return _timestamp(task.completed_at)
    return None


def main_image_newer_than_video(db, shot) -> bool:
    """Only compare real current artifacts; unrelated Shot edits do not affect this flag."""
    if not shot.image_url:
        return False

    image_time = _file_timestamp(shot.image_url, shot.image_path)
    if image_time is None:
        image_time = _task_timestamp(db, shot.image_task_id, shot.image_url)

    video_time = _file_timestamp(shot.video_url)
    if video_time is None and shot.video_url:
        try:
            plan = json.loads(shot.video_director_plan or "{}")
        except (TypeError, ValueError):
            plan = {}
        if plan.get("merged_video_url") == shot.video_url:
            video_time = _timestamp(plan.get("merged_at"))
        if video_time is None:
            video_time = _task_timestamp(db, shot.video_task_id, shot.video_url)
    if video_time is None:
        video_time = _last_completed_shot_video_time(db, shot.id)

    return image_time is not None and video_time is not None and image_time > video_time
