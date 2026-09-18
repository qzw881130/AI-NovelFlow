"""Retired index-based cross-Shot transition entry; existing files remain historical assets."""
from datetime import datetime
from app.core.database import SessionLocal
from app.models.task import Task


async def generate_transition_video_task(task_id,novel_id,chapter_id,from_index,to_index,workflow_id,duration_seconds=None,frame_count=49):
    db=SessionLocal()
    try:
        task=db.get(Task,task_id)
        if task and task.status in {'pending','running'}:
            task.status,task.error_message,task.completed_at='failed','LEGACY_INDEX_TRANSITION_RETIRED',datetime.utcnow();db.commit()
    finally:db.close()
