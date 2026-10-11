"""Notification configuration and delivery records, stored in the application database."""
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    id = Column(String, primary_key=True, default="default")
    page_sound_enabled = Column(Boolean, nullable=False, default=True)
    sound_id = Column(String, nullable=False, default="chime")
    volume = Column(Float, nullable=False, default=0.7)
    feishu_enabled = Column(Boolean, nullable=False, default=False)
    feishu_webhook_encrypted = Column(Text, nullable=True)
    feishu_secret_encrypted = Column(Text, nullable=True)
    telegram_enabled = Column(Boolean, nullable=False, default=False)
    telegram_token_encrypted = Column(Text, nullable=True)
    telegram_chat_id_encrypted = Column(Text, nullable=True)
    event_switches = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_code = Column(String, nullable=False)
    channel = Column(String, nullable=False)
    status = Column(String, nullable=False)
    detail = Column(String, nullable=True)
    is_test = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BusinessEvent(Base):
    """Business facts survive disabled subscriptions and failed deliveries."""
    __tablename__ = "business_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    dedupe_key = Column(String, nullable=False, unique=True)
    event_type = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())
    novel_id = Column(String, index=True)
    chapter_id = Column(String, index=True)
    shot_id = Column(String, index=True)
    visual_state_id = Column(String)
    clip_id = Column(String)
    task_id = Column(String, index=True)
    review_id = Column(String, index=True)
    llm_log_id = Column(String)
    status = Column(String, nullable=False, index=True)
    raw_status = Column(String)
    needs_attention = Column(Boolean, nullable=False, default=False, index=True)
    source = Column(String, nullable=False)
    trigger = Column(String)
    message = Column(Text)
    details_json = Column(Text, nullable=False, default="{}")
    is_test = Column(Boolean, nullable=False, default=False)
    historical = Column(Boolean, nullable=False, default=False)
    notification_status = Column(String, nullable=False, default="pending", index=True)
    notification_result = Column(Text)
