"""Versioned ChapterScope split receipts. Legacy Shots have no invented source record."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Integer, JSON, DateTime, ForeignKey, Index, text
from app.core.database import Base
from sqlalchemy.orm import relationship


class ChapterShotSplitRun(Base):
    __tablename__ = "chapter_shot_split_runs"
    __table_args__ = (Index("uq_running_chapter_shot_split", "chapter_id", unique=True,
        sqlite_where=text("status = 'RUNNING'"), postgresql_where=text("status = 'RUNNING'")),)
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    novel_id = Column(String, nullable=False, index=True)
    chapter_id = Column(String, ForeignKey("chapters.id"), nullable=False, index=True)
    task_id = Column(String, nullable=False, unique=True)
    version = Column(String, nullable=False)
    status = Column(String, nullable=False)
    inputs = Column(JSON, nullable=False)
    input_hash = Column(String, nullable=False)
    call = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=False, default=dict)
    result_hash = Column(String, nullable=True)
    issues = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    chapter = relationship("Chapter", back_populates="shot_split_runs")
    sources = relationship("ShotSource", cascade="all, delete-orphan")


class ShotSource(Base):
    __tablename__ = "shot_sources"
    shot_id = Column(String, ForeignKey("shots.id"), primary_key=True)
    run_id = Column(String, ForeignKey("chapter_shot_split_runs.id"), nullable=False, index=True)
    source_start = Column(Integer, nullable=False)
    source_end = Column(Integer, nullable=False)
    source_hash = Column(String, nullable=False)
    evidence = Column(JSON, nullable=False)
    ranges = Column(JSON, nullable=False)
    bindings = Column(JSON, nullable=False)
    snapshot = Column(JSON, nullable=False)
    audio_snapshot = Column(JSON, nullable=False)
    treatment_contract = Column(JSON, nullable=True)
    source_contract = Column(JSON(none_as_null=True), nullable=True)
    seal = Column(String, nullable=False)
