"""Authorized authoring revisions; the original LLM ShotSource is never rewritten."""
from datetime import datetime
from sqlalchemy import Column, String, Integer, JSON, DateTime, UniqueConstraint
from app.core.database import Base


class ShotRevision(Base):
    __tablename__ = 'shot_revisions'
    __table_args__ = (UniqueConstraint('shot_id', 'base_run_id', 'revision'),)
    id = Column(String, primary_key=True)
    shot_id = Column(String, nullable=False, index=True)
    novel_id = Column(String, nullable=False, index=True)
    chapter_id = Column(String, nullable=False, index=True)
    base_run_id = Column(String, nullable=False)
    task_id = Column(String, nullable=False, unique=True)
    parent_id = Column(String, nullable=True)
    revision = Column(Integer, nullable=False)
    origin = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    seal = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ShotRevisionHead(Base):
    __tablename__ = 'shot_revision_heads'
    shot_id = Column(String, primary_key=True)
    base_run_id = Column(String, nullable=False)
    revision_id = Column(String, nullable=True)
    revision = Column(Integer, nullable=False, default=0)
