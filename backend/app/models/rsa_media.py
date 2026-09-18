"""Task-owned image execution and immutable #06/#09 lineage artifacts."""
from datetime import datetime
from sqlalchemy import Column, String, Integer, JSON, DateTime, Index, text
from app.core.database import Base


class RsaImageAttempt(Base):
    __tablename__ = "rsa_image_attempts"
    __table_args__ = (Index("uq_active_rsa_image_target", "shot_id", "stage", "frame_index", unique=True,
        sqlite_where=text("status IN ('PENDING','RUNNING')"), postgresql_where=text("status IN ('PENDING','RUNNING')")),)
    id = Column(String, primary_key=True)
    novel_id = Column(String, nullable=False, index=True)
    chapter_id = Column(String, nullable=False)
    shot_id = Column(String, nullable=False, index=True)
    stage = Column(String, nullable=False)  # SHOT / KEYFRAME
    frame_index = Column(Integer, nullable=False, default=-1)
    rsa_id = Column(String, nullable=False)
    rsa_hash = Column(String, nullable=False)
    status = Column(String, nullable=False)
    inputs = Column(JSON, nullable=False)
    input_hash = Column(String, nullable=False)
    execution = Column(JSON, nullable=False, default=dict)
    claim_token = Column(String, nullable=True)
    artifact_id = Column(String, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class RsaMediaArtifact(Base):
    __tablename__ = "rsa_media_artifacts"
    id = Column(String, primary_key=True)
    task_id = Column(String, nullable=False, unique=True)
    shot_id = Column(String, nullable=False, index=True)
    rsa_id = Column(String, nullable=False, index=True)
    stage = Column(String, nullable=False)
    frame_index = Column(Integer, nullable=False)
    data = Column(JSON, nullable=False)
    seal = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
