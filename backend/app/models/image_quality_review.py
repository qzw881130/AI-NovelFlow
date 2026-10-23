"""Independent, immutable-per-attempt assessment of a generated image."""
import uuid

from sqlalchemy import Column, DateTime, Index, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class ImageQualityReview(Base):
    __tablename__ = "image_quality_reviews"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending")
    overall = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    dimensions_json = Column(Text, nullable=True)
    issues_json = Column(Text, nullable=True)
    input_snapshot_json = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)
    template_id = Column(String, nullable=True)
    template_name = Column(String, nullable=True)
    template_version = Column(String, nullable=True)
    template_text = Column(Text, nullable=True)
    llm_log_id = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    model = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    trigger = Column(String, nullable=False, default="manual")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


Index("ix_image_quality_reviews_task_created", ImageQualityReview.task_id, ImageQualityReview.created_at)
