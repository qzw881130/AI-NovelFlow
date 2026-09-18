"""Compatibility names only; production images are owned by the RSA worker."""
from datetime import datetime
from app.core.database import SessionLocal
from app.models.task import Task
from app.models.rsa_media import RsaImageAttempt


def enqueue_shot_image_task(task_id,novel_id,chapter_id,shot_index,shot_description,workflow_id):
    # This function cannot manufacture a new execution from an old task/name/index.
    db=SessionLocal()
    try:
        task=db.get(Task,task_id)
        if task and task.status in {'pending','running'} and not db.get(RsaImageAttempt,task_id):
            task.status,task.error_message,task.completed_at='failed','LEGACY_IMAGE_ENTRY_RETIRED',datetime.utcnow();db.commit()
    finally:db.close()


async def generate_shot_image_task(task_id,novel_id,chapter_id,shot_index,shot_description,workflow_id):
    enqueue_shot_image_task(task_id,novel_id,chapter_id,shot_index,shot_description,workflow_id)
