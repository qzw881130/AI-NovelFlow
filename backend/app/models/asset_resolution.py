"""Authoritative identity metadata, resolution receipts and Chapter memberships."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Integer, Float, Boolean, Text, JSON, DateTime, ForeignKey, UniqueConstraint, CheckConstraint, Index, text
from sqlalchemy.orm import relationship
from app.core.database import Base


def uid():
    return str(uuid4())


class CharacterIdentity(Base):
    __tablename__ = "character_identities"
    __table_args__ = (CheckConstraint("entity_type IN ('INDIVIDUAL','GROUP')"),)
    character_id = Column(String, ForeignKey("characters.id"), primary_key=True)
    novel_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    group_size_hint = Column(Integer, nullable=True)
    context = Column(JSON, nullable=False, default=dict)
    provenance = Column(JSON, nullable=False)
    character = relationship("Character", back_populates="identity")


class CharacterAlias(Base):
    __tablename__ = "character_aliases"
    __table_args__ = (
        UniqueConstraint("character_id", "alias", "alias_type"),
        CheckConstraint("alias_type IN ('STRONG','CONTEXTUAL')"),
        Index("uq_character_strong_alias", "novel_id", "alias", unique=True,
              sqlite_where=text("alias_type = 'STRONG'"), postgresql_where=text("alias_type = 'STRONG'")),
    )
    id = Column(String, primary_key=True, default=uid)
    novel_id = Column(String, nullable=False, index=True)
    character_id = Column(String, ForeignKey("characters.id"), nullable=False, index=True)
    alias = Column(String, nullable=False)
    alias_type = Column(String, nullable=False)
    scope = Column(JSON, nullable=False, default=dict)
    provenance = Column(JSON, nullable=False)
    character = relationship("Character", back_populates="aliases")


class AssetResolutionLease(Base):
    __tablename__ = "asset_resolution_leases"
    novel_id = Column(String, primary_key=True)
    owner = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class AssetResolutionRun(Base):
    __tablename__ = "asset_resolution_runs"
    __table_args__ = (CheckConstraint("status IN ('RUNNING','SUCCEEDED','NEEDS_REVIEW','FAILED')"),)
    id = Column(String, primary_key=True, default=uid)
    novel_id = Column(String, nullable=False, index=True)
    chapter_id = Column(String, ForeignKey("chapters.id"), nullable=False, index=True)
    task_id = Column(String, nullable=False, unique=True)
    resolver_version = Column(String, nullable=False)
    policy_hash = Column(String, nullable=False)
    kinds = Column(JSON, nullable=False)
    inputs = Column(JSON, nullable=False)
    input_hash = Column(String, nullable=False)
    catalog_hash = Column(String, nullable=False)
    status = Column(String, nullable=False, default="RUNNING")
    issues = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    chapter = relationship("Chapter", back_populates="resolution_runs")
    decisions = relationship("AssetResolutionDecision", back_populates="run", cascade="all, delete-orphan")
    omissions = relationship("AssetResolutionOmission", back_populates="run", cascade="all, delete-orphan")


class AssetResolutionDecision(Base):
    """AMBIGUOUS + PENDING_REVIEW rows are the review queue; no asset is created for them."""
    __tablename__ = "asset_resolution_decisions"
    __table_args__ = (
        UniqueConstraint("run_id", "candidate_id"),
        CheckConstraint("status IN ('PLANNED','PENDING_REVIEW','APPLIED','IGNORED')"),
    )
    id = Column(String, primary_key=True, default=uid)
    run_id = Column(String, ForeignKey("asset_resolution_runs.id"), nullable=False, index=True)
    candidate_id = Column(String, nullable=False)
    asset_type = Column(String, nullable=False)
    candidate = Column(JSON, nullable=False)
    resolution = Column(String, nullable=False)
    match_type = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    reason = Column(Text, nullable=False)
    llm_used = Column(Boolean, nullable=False)
    shortlist = Column(JSON, nullable=False, default=list)
    call = Column(JSON, nullable=True)
    plan = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="PLANNED")
    asset_id = Column(String, nullable=True)
    manual_action = Column(JSON, nullable=True)
    run = relationship("AssetResolutionRun", back_populates="decisions")


class AssetResolutionOmission(Base):
    """Program-derived receipt for a direct-parent binding omitted by the current parse."""
    __tablename__ = "asset_resolution_omissions"
    __table_args__ = (
        UniqueConstraint("run_id", "asset_type", "asset_id"),
        CheckConstraint("asset_type IN ('characters','scenes','props')"),
        CheckConstraint("status IN ('CARRIED','PENDING_REVIEW')"),
    )
    id = Column(String, primary_key=True, default=uid)
    run_id = Column(String, ForeignKey("asset_resolution_runs.id"), nullable=False, index=True)
    asset_type = Column(String, nullable=False)
    asset_id = Column(String, nullable=False)
    prior_binding_id = Column(String, nullable=False)
    prior_resolution_run_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    reason_code = Column(String, nullable=False)
    proof = Column(JSON, nullable=False)
    proof_hash = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    run = relationship("AssetResolutionRun", back_populates="omissions")


class BindingColumns:
    id = Column(String, primary_key=True, default=uid)
    novel_id = Column(String, nullable=False, index=True)
    chapter_id = Column(String, ForeignKey("chapters.id"), nullable=False, index=True)
    resolution_run_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    chapter_role = Column(String, nullable=True)
    resolution_method = Column(String, nullable=False)
    resolution_confidence = Column(Float, nullable=False)
    source_evidence = Column(JSON, nullable=False)
    provenance = Column(JSON, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ChapterCharacterBinding(BindingColumns, Base):
    __tablename__ = "chapter_character_bindings"
    __table_args__ = (UniqueConstraint("chapter_id", "character_id"),)
    character_id = Column(String, ForeignKey("characters.id"), nullable=False)


class ChapterSceneBinding(BindingColumns, Base):
    __tablename__ = "chapter_scene_bindings"
    __table_args__ = (UniqueConstraint("chapter_id", "scene_id"),)
    scene_id = Column(String, ForeignKey("scenes.id"), nullable=False)


class ChapterPropBinding(BindingColumns, Base):
    __tablename__ = "chapter_prop_bindings"
    __table_args__ = (UniqueConstraint("chapter_id", "prop_id"),)
    prop_id = Column(String, ForeignKey("props.id"), nullable=False)


class ChapterCharacterAppearanceEvent(Base):
    """Identity-linked proposals. Phase3 must locate them before timeline use."""
    __tablename__ = "chapter_character_appearance_events"
    __table_args__ = (UniqueConstraint("candidate_id", "event_key"),)
    id = Column(String, primary_key=True, default=uid)
    novel_id = Column(String, nullable=False)
    chapter_id = Column(String, ForeignKey("chapters.id"), nullable=False, index=True)
    character_id = Column(String, ForeignKey("characters.id"), nullable=False)
    candidate_id = Column(String, nullable=False)
    resolution_run_id = Column(String, nullable=False)
    event_key = Column(String, nullable=False)
    change_type = Column(String, nullable=False)
    appearance_description = Column(Text, nullable=True)
    source_evidence = Column(JSON, nullable=False)
    source_start = Column(Integer, nullable=True)
    source_end = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="PENDING_LOCATION")
    resolved_appearance_id = Column(String, nullable=True)
    location_proof = Column(JSON, nullable=True)
    located_source_hash = Column(String, nullable=True)
    reviews = relationship("AppearanceEventReview", cascade="all, delete-orphan")
