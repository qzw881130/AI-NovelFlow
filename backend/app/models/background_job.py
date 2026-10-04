import uuid

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class BackgroundJob(Base):
    """Durable execution descriptor for a serialized background worker."""

    __tablename__ = "background_jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    task_id = Column(String, nullable=False, index=True)
    queue_name = Column(String, nullable=False, index=True)
    handler = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False, default="{}")
    status = Column(String, nullable=False, default="queued", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


Index(
    "ix_background_jobs_queue_status_created",
    BackgroundJob.queue_name,
    BackgroundJob.status,
    BackgroundJob.created_at,
)
Index(
    "ix_background_jobs_task_active",
    BackgroundJob.task_id,
    BackgroundJob.status,
)
