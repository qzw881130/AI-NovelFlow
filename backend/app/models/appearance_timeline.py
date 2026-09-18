"""Logical appearance definitions and versioned source-position timelines."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Text, JSON, DateTime, Integer, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base


def uid():
    return str(uuid4())


class CharacterAppearance(Base):
    __tablename__ = "character_appearances"
    __table_args__ = (CheckConstraint("status IN ('NEEDS_GENERATION','GENERATING','READY','FAILED','REJECTED')"),)
    id = Column(String, primary_key=True, default=uid)
    novel_id = Column(String, nullable=False, index=True)
    character_id = Column(String, ForeignKey("characters.id"), nullable=False, index=True)
    source_chapter_id = Column(String, nullable=False)
    source_event_id = Column(String, nullable=False)
    definition_hash = Column(String, nullable=False, unique=True)
    definition = Column(JSON, nullable=False)
    description = Column(Text, nullable=False)
    previous_appearance_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="NEEDS_GENERATION")
    reference_image_url = Column(String, nullable=True)
    workflow_id = Column(String, nullable=True)
    task_id = Column(String, nullable=True)
    reference_image_revision_id = Column(String, nullable=True)
    generation_revision = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AppearanceEventReview(Base):
    __tablename__ = "appearance_event_reviews"
    id = Column(String, primary_key=True, default=uid)
    event_id = Column(String, ForeignKey("chapter_character_appearance_events.id"), nullable=False, index=True)
    source_hash = Column(String, nullable=False)
    proposal_hash = Column(String, nullable=False)
    action = Column(String, nullable=False)
    source_start = Column(Integer, nullable=True)
    source_end = Column(Integer, nullable=True)
    evidence_text = Column(Text, nullable=True)
    appearance_description = Column(Text, nullable=True)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AppearanceTimelineRun(Base):
    __tablename__ = "appearance_timeline_runs"
    __table_args__ = (CheckConstraint("status IN ('RUNNING','SUCCEEDED','NEEDS_REVIEW','FAILED')"),)
    id = Column(String, primary_key=True, default=uid)
    novel_id = Column(String, nullable=False, index=True)
    chapter_id = Column(String, ForeignKey("chapters.id"), nullable=False, index=True)
    task_id = Column(String, nullable=False, unique=True)
    resolver_version = Column(String, nullable=False)
    input_hash = Column(String, nullable=True)
    inputs = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="RUNNING")
    issues = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    chapter = relationship("Chapter", back_populates="appearance_timeline_runs")
