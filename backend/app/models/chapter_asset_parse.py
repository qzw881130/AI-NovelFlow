"""Versioned extraction evidence. Candidates are not Book assets or bindings."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Integer, Index, UniqueConstraint, CheckConstraint, text
from sqlalchemy.orm import relationship

from app.core.database import Base


class ChapterAssetParseRun(Base):
    __tablename__ = "chapter_asset_parse_runs"
    __table_args__ = (
        CheckConstraint("status IN ('RUNNING','SUCCEEDED','NEEDS_REVIEW','FAILED')"),
        Index("uq_chapter_asset_parse_running", "chapter_id", unique=True,
              sqlite_where=text("status = 'RUNNING'"), postgresql_where=text("status = 'RUNNING'")),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    novel_id = Column(String, nullable=False, index=True)
    chapter_id = Column(String, ForeignKey("chapters.id"), nullable=False, index=True)
    task_id = Column(String, nullable=False, unique=True)
    parser_version = Column(String, nullable=False)
    kinds = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="RUNNING")
    source_title = Column(Text, nullable=False)
    source_number = Column(Integer, nullable=False)
    source_content = Column(Text, nullable=False)
    source_hash = Column(String, nullable=False)
    calls = Column(JSON, nullable=False, default=list)
    issues = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    chapter = relationship("Chapter", back_populates="asset_parse_runs")
    candidates = relationship("ChapterAssetCandidate", cascade="all, delete-orphan", back_populates="run")


class ChapterAssetCandidate(Base):
    __tablename__ = "chapter_asset_candidates"
    __table_args__ = (
        UniqueConstraint("run_id", "asset_type", "name", name="uq_parse_candidate_name"),
        CheckConstraint("asset_type IN ('characters','scenes','props')"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    run_id = Column(String, ForeignKey("chapter_asset_parse_runs.id"), nullable=False, index=True)
    asset_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    group_size_hint = Column(Integer, nullable=True)
    payload = Column(JSON, nullable=False)
    validation_status = Column(String, nullable=False)
    issues = Column(JSON, nullable=False, default=list)
    run = relationship("ChapterAssetParseRun", back_populates="candidates")
