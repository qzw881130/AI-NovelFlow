from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class ShotAudioEvent(Base):
    __tablename__ = "shot_audio_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    shot_id = Column(String, ForeignKey("shots.id"), nullable=False, index=True)
    event_order = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False, default="DIALOGUE")
    voice_owner_character_id = Column(String, nullable=True, index=True)
    voice_owner_name = Column(String, nullable=False, default="")
    visible_speaker_character_id = Column(String, nullable=True, index=True)
    visible_speaker_name = Column(String, nullable=True)
    requires_visible_lipsync = Column(Boolean, default=False)
    text = Column(Text, nullable=False, default="")
    emotion_prompt = Column(Text, nullable=True)
    pause_after = Column(String, default="NONE")
    tts_status = Column(String, default="NOT_GENERATED", index=True)
    text_hash = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tts_assets = relationship("AudioEventTTSAsset", back_populates="audio_event", cascade="all, delete-orphan")


class AudioEventTTSAsset(Base):
    __tablename__ = "audio_event_tts_assets"

    id = Column(String, primary_key=True, default=generate_uuid)
    audio_event_id = Column(String, ForeignKey("shot_audio_events.id"), nullable=False, index=True)
    provider = Column(String, nullable=True)
    model = Column(String, nullable=True)
    voice_id = Column(String, nullable=True)
    audio_url = Column(String, nullable=True)
    audio_path = Column(String, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    sample_rate = Column(Integer, nullable=True)
    channels = Column(Integer, nullable=True)
    file_size = Column(Integer, nullable=True)
    content_hash = Column(String, nullable=True, index=True)
    text_hash = Column(String, nullable=True, index=True)
    config_json = Column(Text, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, default=True, index=True)
    status = Column(String, default="READY", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    audio_event = relationship("ShotAudioEvent", back_populates="tts_assets")


class ShotAudioTimeline(Base):
    __tablename__ = "shot_audio_timelines"

    id = Column(String, primary_key=True, default=generate_uuid)
    shot_id = Column(String, ForeignKey("shots.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False, default=1)
    total_duration = Column(Float, nullable=False, default=0)
    audio_required_duration = Column(Float, nullable=True)
    status = Column(String, default="NOT_READY", index=True)
    generated_from_hash = Column(String, nullable=True, index=True)
    audio_summary_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    events = relationship("ShotAudioTimelineEvent", back_populates="timeline", cascade="all, delete-orphan")


class ShotAudioTimelineEvent(Base):
    __tablename__ = "shot_audio_timeline_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    timeline_id = Column(String, ForeignKey("shot_audio_timelines.id"), nullable=False, index=True)
    audio_event_id = Column(String, ForeignKey("shot_audio_events.id"), nullable=False, index=True)
    event_order = Column(Integer, nullable=False)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    event_type = Column(String, nullable=False)
    voice_owner_character_id = Column(String, nullable=True)
    voice_owner_name = Column(String, nullable=False, default="")
    visible_speaker_character_id = Column(String, nullable=True)
    visible_speaker_name = Column(String, nullable=True)
    requires_visible_lipsync = Column(Boolean, default=False)
    tts_asset_id = Column(String, ForeignKey("audio_event_tts_assets.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    timeline = relationship("ShotAudioTimeline", back_populates="events")


Index("ix_shot_audio_events_shot_order", ShotAudioEvent.shot_id, ShotAudioEvent.event_order)
Index("ix_audio_event_tts_current", AudioEventTTSAsset.audio_event_id, AudioEventTTSAsset.is_current)
Index("ix_shot_audio_timelines_shot_revision", ShotAudioTimeline.shot_id, ShotAudioTimeline.revision)
Index("ix_shot_audio_timeline_events_timeline_order", ShotAudioTimelineEvent.timeline_id, ShotAudioTimelineEvent.event_order)
