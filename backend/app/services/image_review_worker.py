"""Optional review queue using the existing review records and worker loop."""
import asyncio
import logging
from datetime import datetime, timezone
from threading import RLock

from sqlalchemy import exists

from app.core.database import SessionLocal
from app.models.image_quality_review import ImageQualityReview
from app.models.system_config import SystemConfig
from app.models.task import Task
from app.services.image_quality_review import (
    IMAGE_TYPES, create_image_review, current_image_reviews, execute_image_review,
)

logger = logging.getLogger(__name__)
_enqueue_lock = RLock()


def enqueue_automatic_review(db, task_id):
    """Completion-event entry point. No LLM/image processing on the generation path."""
    with _enqueue_lock:
        config = db.get(SystemConfig, "default")
        if not config or not config.auto_image_review_enabled:
            return None
        task = db.get(Task, task_id)
        if not task or task.type not in IMAGE_TYPES or task.status != "completed" or not task.result_url:
            return None
        # A delayed/replayed historical completion event must obey the same
        # activation boundary as the polling fallback. SQLite returns naive UTC.
        if config.auto_image_review_enabled_at:
            enabled_at = config.auto_image_review_enabled_at.replace(tzinfo=None)
            completed_at = task.completed_at.replace(tzinfo=None) if task.completed_at else None
            if completed_at is None or completed_at < enabled_at:
                return None
        current = current_image_reviews(db, [{"taskId": task.id, "imageUrl": task.result_url}])[0]
        if current["reviewId"]:
            return db.get(ImageQualityReview, current["reviewId"])
        return create_image_review(db, task.id, trigger="automatic")


def image_generation_completed(task_id):
    """Called only AFTER generation commits, in an independent transaction.

    Review persistence errors must never reach the generation failure handler.
    The existing polling fallback covers a temporarily failed enqueue.
    """
    try:
        with SessionLocal() as db:
            return enqueue_automatic_review(db, task_id)
    except Exception:
        logger.exception("图片已保存；自动评审入队失败，不改变生成任务 %s", task_id)
        return None


async def process_review_queue(db):
    config = db.get(SystemConfig, "default")
    if not config or not config.auto_image_review_enabled:
        return None
    # Preserve the V1 polling fallback for other image types and missed events.
    if config.auto_image_review_enabled_at:
        tasks = db.query(Task).filter(
            Task.type.in_(IMAGE_TYPES), Task.status == "completed",
            Task.completed_at >= config.auto_image_review_enabled_at,
            Task.result_url.isnot(None), Task.result_url != "",
            Task.prompt_text.isnot(None), Task.prompt_text != "",
            ~exists().where(ImageQualityReview.task_id == Task.id),
        ).order_by(Task.completed_at.asc()).limit(20).all()
        for task in tasks:
            enqueue_automatic_review(db, task.id)
    pending = db.query(ImageQualityReview).filter_by(status="pending", trigger="automatic").order_by(
        ImageQualityReview.created_at.asc(), ImageQualityReview.id.asc()).first()
    if pending:
        return await execute_image_review(db, pending.id)
    return None


async def auto_review_loop():
    # Never silently resubmit an LLM request interrupted by an API restart.
    with SessionLocal() as db:
        for review in db.query(ImageQualityReview).filter_by(status="running").all():
            review.status = "error"
            review.error_message = "评审进程中断，请手动重新评审；图片生成不受影响"
            review.completed_at = datetime.now(timezone.utc)
        db.commit()
    while True:
        try:
            with SessionLocal() as db:
                await process_review_queue(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("自动图片评审失败，不影响原生成任务")
        await asyncio.sleep(5)
