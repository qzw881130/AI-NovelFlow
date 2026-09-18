"""Generation attempts and immutable image revisions; no modification of Character base assets."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, ForeignKey, UniqueConstraint, Index, text
from app.core.database import Base


class AppearanceGeneration(Base):
    __tablename__ = "appearance_generations"
    __table_args__ = (Index("uq_active_appearance_generation", "appearance_id", unique=True,
        sqlite_where=text("status IN ('PENDING','RUNNING')"), postgresql_where=text("status IN ('PENDING','RUNNING')")),)
    id = Column(String, primary_key=True)  # equals Task ID; ledger survives task-list cleanup
    appearance_id = Column(String, ForeignKey("character_appearances.id"), nullable=False, index=True)
    novel_id = Column(String, nullable=False, index=True)
    character_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    inputs = Column(JSON, nullable=False)
    input_hash = Column(String, nullable=False)
    execution = Column(JSON, nullable=False, default=dict)
    claim_token = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class AppearanceImageRevision(Base):
    __tablename__ = "appearance_image_revisions"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    appearance_id = Column(String, ForeignKey("character_appearances.id"), nullable=False, index=True)
    generation_id = Column(String, nullable=False, unique=True)
    image_url = Column(String, nullable=False)
    sha256 = Column(String, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    receipt = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AppearanceShotUsage(Base):
    """Retired Phase4 placeholder. Runtime demand comes only from Phase6 ShotAppearanceDemand."""
    __tablename__ = "appearance_shot_usages"
    __table_args__ = (UniqueConstraint("shot_id", "character_id"),)
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    novel_id = Column(String, nullable=False)
    chapter_id = Column(String, nullable=False, index=True)
    shot_id = Column(String, ForeignKey("shots.id"), nullable=False)
    character_id = Column(String, nullable=False)
    appearance_id = Column(String, nullable=False)
    timeline_run_id = Column(String, nullable=False)
    source_hash = Column(String, nullable=False)
    source_start = Column(Integer, nullable=False)
    source_end = Column(Integer, nullable=False)
    shot_hash = Column(String, nullable=False)
    producer = Column(String, nullable=False)
    producer_version = Column(String, nullable=False)
    status = Column(String, nullable=False, default="CURRENT")
