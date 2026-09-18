from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.novel import Character, Chapter
from app.models.shot import Shot
from app.models.appearance_timeline import CharacterAppearance as Appearance
from app.models.appearance_generation import AppearanceGeneration as Generation, AppearanceImageRevision as Revision
from app.schemas.appearance_generation import GenerateAppearanceRequest, RejectAppearanceRequest, GenerateUsedAppearancesRequest
from app.services.appearance_generation_service import AppearanceGenerationService
from app.services.appearance_image_contract import current_appearance, source_reference, load_prompt, ready_revision
from app.services.appearance_usage import plan_used_missing

router = APIRouter()
PREFIX = "/{novel_id}/characters/{character_id}/appearances"


def actor_in_scope(db, novel_id, character_id):
    actor = db.query(Character).filter_by(id=character_id, novel_id=novel_id).first()
    if not actor:
        raise HTTPException(404, "角色不存在")
    return actor


def asset_in_scope(db, novel_id, character_id, appearance_id):
    actor_in_scope(db, novel_id, character_id)
    asset = db.query(Appearance).filter_by(id=appearance_id, novel_id=novel_id, character_id=character_id).first()
    if not asset:
        raise HTTPException(404, "角色外观不存在")
    return asset


def serialize_asset(db, asset):
    current, source, blocker = False, None, None
    image_ready, image_error = False, None
    if asset.status == "READY":
        try:
            ready_revision(db, asset, load_prompt()["definition"])
            image_ready = True
        except (HTTPException, ValueError) as exc:
            image_error = str(exc.detail if isinstance(exc, HTTPException) else exc)
    try:
        _, actor, _ = current_appearance(db, asset.id)
        current = True
        _, source = source_reference(db, asset, actor, load_prompt()["definition"])
    except (HTTPException, ValueError) as exc:
        blocker = str(exc.detail if isinstance(exc, HTTPException) else exc)
    return {"id": asset.id, "description": asset.description, "status": asset.status, "logicalCurrent": current,
        "sourceChapterId": asset.source_chapter_id, "sourceEventId": asset.source_event_id,
        "previousAppearanceId": asset.previous_appearance_id, "definitionHash": asset.definition_hash,
        "imageUrl": asset.reference_image_url if image_ready else None, "imageReady": image_ready,
        "imageRevisionId": asset.reference_image_revision_id, "generationRevision": asset.generation_revision,
        "taskId": asset.task_id, "lastError": image_error or asset.last_error, "source": source, "generationBlocker": blocker}


@router.get(PREFIX)
def list_appearances(novel_id: str, character_id: str, db: Session = Depends(get_db)):
    actor = actor_in_scope(db, novel_id, character_id)
    assets = db.query(Appearance).filter_by(novel_id=novel_id, character_id=character_id).order_by(Appearance.created_at, Appearance.id).all()
    return {"success": True, "data": {"characterId": actor.id, "base": {"kind": "BASE", "imageUrl": actor.image_url,
        "description": actor.appearance, "status": "AVAILABLE" if actor.image_url else "MISSING"},
        "appearances": [serialize_asset(db, asset) for asset in assets]}}


@router.get(PREFIX + "/{appearance_id}")
def appearance_detail(novel_id: str, character_id: str, appearance_id: str, db: Session = Depends(get_db)):
    asset = asset_in_scope(db, novel_id, character_id, appearance_id)
    attempts = db.query(Generation).filter_by(appearance_id=asset.id).order_by(Generation.created_at.desc()).all()
    revisions = db.query(Revision).filter_by(appearance_id=asset.id).order_by(Revision.created_at.desc()).all()
    return {"success": True, "data": {**serialize_asset(db, asset), "definition": asset.definition,
        "attempts": [{"id": g.id, "status": g.status, "inputHash": g.input_hash, "inputs": g.inputs,
            "execution": g.execution, "error": g.error, "createdAt": g.created_at, "completedAt": g.completed_at} for g in attempts],
        "revisions": [{"id": r.id, "generationId": r.generation_id, "imageUrl": r.image_url, "sha256": r.sha256,
            "width": r.width, "height": r.height, "receipt": r.receipt} for r in revisions]}}


@router.post(PREFIX + "/{appearance_id}/generate")
def generate(novel_id: str, character_id: str, appearance_id: str, request: GenerateAppearanceRequest, db: Session = Depends(get_db)):
    try:
        return AppearanceGenerationService(db).enqueue(novel_id, character_id, appearance_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post(PREFIX + "/{appearance_id}/reject")
def reject(novel_id: str, character_id: str, appearance_id: str, request: RejectAppearanceRequest, db: Session = Depends(get_db)):
    asset = asset_in_scope(db, novel_id, character_id, appearance_id)
    return AppearanceGenerationService(db).reject(asset, request.expected_generation_id, request.expected_image_revision_id, request.reason)


@router.post("/{novel_id}/chapters/{chapter_id}/appearances/generate-used-missing")
def generate_used(novel_id: str, chapter_id: str, request: GenerateUsedAppearancesRequest, db: Session = Depends(get_db)):
    plan = plan_used_missing(db, novel_id, chapter_id, request.shot_ids)
    queued = []
    for appearance_id, receipt_ids in plan.pop("eligible").items():
        asset = db.get(Appearance, appearance_id)
        try:
            result = AppearanceGenerationService(db).enqueue(novel_id, asset.character_id, asset.id, usage_ids=receipt_ids)
            queued.append(result["data"])
        except (HTTPException, ValueError) as exc:
            db.rollback()
            plan["blocked"].append({"appearanceId": appearance_id, "code": str(exc.detail if isinstance(exc, HTTPException) else exc)})
    return {"success": not bool(plan["blocked"]), "data": {**plan, "queued": queued}}


@router.get("/{novel_id}/chapters/{chapter_id}/appearances/shot-usage")
def shot_usage(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    if not db.query(Chapter).filter_by(id=chapter_id, novel_id=novel_id).first():
        raise HTTPException(404, "章回不存在")
    shots = db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index, Shot.id).all()
    return {"success": True, "data": [{"shotId": shot.id, "index": shot.index,
        **plan_used_missing(db, novel_id, chapter_id, [shot.id])} for shot in shots]}
