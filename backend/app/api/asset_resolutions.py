from copy import deepcopy
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Character, Chapter, Novel
from app.models.asset_resolution import AssetResolutionRun, CharacterIdentity, CharacterAlias
from app.schemas.asset_resolution import ResolveRequest, ReviewAction, IdentityRequest, AliasRequest, PreviewRequest
from app.services.asset_identity import catalog, load_policy, seed_aliases
from app.services.asset_resolution_service import AssetResolutionService, resolution_response, binding_state, acquire, fence, release
from app.services.chapter_asset_pipeline import attach_timeline

router = APIRouter()
PREFIX = "/{novel_id}/chapters/{chapter_id}"


@router.post(PREFIX + "/asset-resolutions")
async def resolve_assets(novel_id: str, chapter_id: str, data: ResolveRequest, db: Session = Depends(get_db)):
    result = await AssetResolutionService(db).resolve(novel_id, chapter_id, data.kinds, data.force)
    return attach_timeline(db, novel_id, chapter_id, result, data.kinds)


@router.get(PREFIX + "/asset-resolutions")
def get_resolutions(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    if not db.query(Chapter.id).filter_by(id=chapter_id, novel_id=novel_id).first():
        raise HTTPException(404, "章回不存在")
    runs = db.query(AssetResolutionRun).filter_by(novel_id=novel_id, chapter_id=chapter_id).order_by(
        AssetResolutionRun.created_at.desc(), AssetResolutionRun.id.desc()).all()
    return {"success": True, "data": [resolution_response(db, run) for run in runs]}


@router.get(PREFIX + "/asset-bindings")
def get_bindings(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    data = deepcopy(binding_state(db, novel_id, chapter_id))
    for group in data["assets"].values():
        for binding in group["bindings"]:
            binding["membershipEvidence"] = deepcopy(binding.get("sourceEvidence") or [])
    return {"success": True, "data": data}


@router.post(PREFIX + "/asset-reviews/{decision_id}")
def act_on_review(novel_id: str, chapter_id: str, decision_id: str, data: ReviewAction, db: Session = Depends(get_db)):
    result = AssetResolutionService(db).review(novel_id, chapter_id, decision_id, data)
    return attach_timeline(db, novel_id, chapter_id, result, result["data"]["kinds"])


@router.get("/{novel_id}/identity-catalog")
def identity_catalog(novel_id: str, db: Session = Depends(get_db)):
    if not db.get(Novel, novel_id):
        raise HTTPException(404, "小说不存在")
    assets, fingerprint = catalog(db, novel_id)
    return {"success": True, "data": {"assets": assets, "hash": fingerprint, "genericGroups": load_policy()["rules"]["generic_groups"]}}


@router.post("/{novel_id}/character-identities/{character_id}")
def classify_character(novel_id: str, character_id: str, data: IdentityRequest, db: Session = Depends(get_db)):
    character = db.query(Character).filter_by(id=character_id, novel_id=novel_id).first()
    if not character:
        raise HTTPException(404, "角色不存在")
    if data.entity_type == "GROUP" and data.group_size_hint is not None and data.group_size_hint < 2:
        raise HTTPException(422, "群体数量应>=2或为空")
    if data.entity_type == "INDIVIDUAL" and data.group_size_hint not in (None, 1):
        raise HTTPException(422, "个体数量必须为1")
    owner = str(uuid4())
    acquire(db, novel_id, owner, 120)
    try:
        fence(db, novel_id, owner)
        identity = db.get(CharacterIdentity, character_id)
        if identity and identity.entity_type != data.entity_type:
            raise HTTPException(409, "已确认的身份类型不能由此接口更改")
        if not identity:
            db.add(CharacterIdentity(character_id=character_id, novel_id=novel_id, entity_type=data.entity_type,
                group_size_hint=1 if data.entity_type == "INDIVIDUAL" else data.group_size_hint, context=data.context,
                provenance={"origin": "MANUAL_CLASSIFICATION"}))
            seed_aliases(db, character, load_policy(), {"origin": "MANUAL_CLASSIFICATION"})
        db.commit()
        return {"success": True, "data": {"characterId": character_id, "entityType": data.entity_type}}
    finally:
        release(db, novel_id, owner)


@router.post("/{novel_id}/character-identities/{character_id}/aliases")
def add_alias(novel_id: str, character_id: str, data: AliasRequest, db: Session = Depends(get_db)):
    character = db.query(Character).filter_by(id=character_id, novel_id=novel_id).first()
    if not character or not db.get(CharacterIdentity, character_id):
        raise HTTPException(409, "请先确认同Book角色的身份类型")
    if data.alias_type == "STRONG" and data.scope:
        raise HTTPException(422, "强别名必须是全Book稳定别名；有限作用范围请使用CONTEXTUAL")
    owner = str(uuid4())
    acquire(db, novel_id, owner, 120)
    try:
        fence(db, novel_id, owner)
        alias = data.alias.strip()
        if not alias:
            raise HTTPException(422, "别名不能为空")
        if data.alias_type == "STRONG" and db.query(CharacterAlias.id).filter(CharacterAlias.novel_id == novel_id,
                CharacterAlias.alias == alias, CharacterAlias.alias_type == "STRONG", CharacterAlias.character_id != character_id).first():
            raise HTTPException(409, "强别名已指向另一身份")
        row = db.query(CharacterAlias).filter_by(character_id=character_id, alias=alias, alias_type=data.alias_type).first()
        if not row:
            row = CharacterAlias(novel_id=novel_id, character_id=character_id, alias=alias, alias_type=data.alias_type,
                                 scope=data.scope, provenance={"origin": "MANUAL"})
            db.add(row)
        db.commit()
        return {"success": True, "data": {"id": row.id, "alias": row.alias, "type": row.alias_type}}
    finally:
        release(db, novel_id, owner)


@router.post("/{novel_id}/asset-resolver-preview")
async def preview(novel_id: str, data: PreviewRequest, db: Session = Depends(get_db)):
    """Diagnostic caller-supplied candidate, never published as a Phase1/Binding record."""
    chapter = db.query(Chapter).filter_by(id=data.chapter_id, novel_id=novel_id).first()
    if not chapter or any(item["text"] not in (chapter.content or "") for item in data.candidate["source_evidence"]):
        raise HTTPException(409, "预览候选必须带本章真实原文依据")
    assets, fingerprint = catalog(db, novel_id)
    result = await AssetResolutionService(db).plan(data.asset_type, data.candidate, assets, load_policy(), chapter, [])
    return {"success": True, "data": {"origin": "MANUAL_PREVIEW", "published": False, "catalogHash": fingerprint, **result}}
