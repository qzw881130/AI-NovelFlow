"""Immutable RSA/image versions and logical appearance demand; head is the only mutable pointer."""
from datetime import datetime
from sqlalchemy import Column, String, Integer, JSON, DateTime, Index, UniqueConstraint
from app.core.database import Base


class ResolvedShotAssets(Base):
    __tablename__ = "resolved_shot_assets"
    id = Column(String, primary_key=True)
    shot_id = Column(String, nullable=False, index=True)
    novel_id = Column(String, nullable=False, index=True)
    chapter_id = Column(String, nullable=False, index=True)
    task_id = Column(String, nullable=False, unique=True)
    revision = Column(Integer, nullable=False)
    resolver_version = Column(String, nullable=False)
    status = Column(String, nullable=False)  # RUNNING -> READY / BLOCKED / FAILED, then immutable
    inputs = Column(JSON, nullable=False, default=dict)
    input_hash = Column(String, nullable=True)
    data = Column(JSON, nullable=False, default=dict)
    result_hash = Column(String, nullable=True)
    seal = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class ShotAssetHead(Base):
    __tablename__ = "shot_asset_heads"
    shot_id = Column(String, primary_key=True)
    rsa_id = Column(String, nullable=True)
    revision = Column(Integer, nullable=False, default=0)


class ResolvedImageVersion(Base):
    __tablename__ = "resolved_image_versions"
    id = Column(String, primary_key=True)
    novel_id = Column(String, nullable=False, index=True)
    origin_hash = Column(String, nullable=False, index=True)
    data = Column(JSON, nullable=False)
    seal = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ShotAppearanceDemand(Base):
    __tablename__ = "shot_appearance_demands"
    __table_args__ = (UniqueConstraint("rsa_id", "character_id"), Index("ix_shot_appearance_demand_scope", "shot_id", "appearance_id"))
    id = Column(String, primary_key=True)
    rsa_id = Column(String, nullable=False, index=True)
    novel_id = Column(String, nullable=False)
    chapter_id = Column(String, nullable=False)
    shot_id = Column(String, nullable=False)
    character_id = Column(String, nullable=False)
    appearance_id = Column(String, nullable=False)
    logical_hash = Column(String, nullable=False)
    proof = Column(JSON, nullable=False)
    seal = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
