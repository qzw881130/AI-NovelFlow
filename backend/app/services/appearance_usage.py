"""Phase4 consumes verified Shot demand; Phase6 is responsible for producing receipts.

No receipt is inferred from legacy names, Shot indexes or all Chapter appearances.
"""
from fastapi import HTTPException
from app.models.shot import Shot
from app.models.novel import Chapter
from app.models.appearance_timeline import CharacterAppearance
from app.models.resolved_shot_assets import ShotAppearanceDemand, ResolvedShotAssets, ShotAssetHead
from app.services.chapter_asset_parse_service import digest
from app.services.appearance_image_contract import ready_revision, load_prompt


def shot_fingerprint(shot):
    return digest({key: getattr(shot, key) for key in ("id", "chapter_id", "index", "description", "characters", "scene", "props")})


def verify_usage(db, usage_id, appearance_id):
    from app.services.resolved_shot_assets_service import check_logical_rsa, demand_payload
    receipt = db.get(ShotAppearanceDemand, usage_id)
    if not receipt or receipt.appearance_id != appearance_id or receipt.seal != digest(demand_payload(receipt)):
        raise HTTPException(409, "SHOT_USAGE_UNVERIFIED")
    rsa = check_logical_rsa(db,db.get(ResolvedShotAssets,receipt.rsa_id))
    if ({**demand_payload(receipt),"seal":receipt.seal} not in rsa.data["demands"]
            or receipt.logical_hash != rsa.data["logical_hash"] or receipt.shot_id != rsa.shot_id
            or receipt.novel_id != rsa.novel_id or receipt.chapter_id != rsa.chapter_id
            or receipt.proof["source"] != rsa.inputs["logical"]["source"]):
        raise HTTPException(409,"SHOT_USAGE_RSA_PROOF_CHANGED")
    actor = next((a for a in rsa.inputs["logical"]["characters"] if a["character_id"]==receipt.character_id),None)
    if not actor or actor["appearance_id"] != appearance_id or receipt.proof["actor"] != actor:
        raise HTTPException(409,"SHOT_USAGE_APPEARANCE_CHANGED")
    return receipt


def plan_used_missing(db, novel_id, chapter_id, shot_ids):
    plan = {"eligible": {}, "skipped": [], "blocked": []}
    for shot_id in dict.fromkeys(shot_ids):
        shot = db.get(Shot, shot_id)
        chapter = db.get(Chapter, chapter_id)
        if not shot or not chapter or chapter.novel_id != novel_id or shot.chapter_id != chapter_id:
            plan["blocked"].append({"shotId": shot_id, "code": "SHOT_SCOPE_MISMATCH"}); continue
        from app.services.resolved_shot_assets_service import check_logical_rsa
        head = db.get(ShotAssetHead,shot_id)
        try:
            if not head or not head.rsa_id:
                raise HTTPException(409,"SHOT_USAGE_NOT_READY")
            rsa = check_logical_rsa(db,db.get(ResolvedShotAssets,head.rsa_id))
            receipts = db.query(ShotAppearanceDemand).filter_by(rsa_id=rsa.id,shot_id=shot_id).all()
            expected = {(a["character_id"],a["appearance_id"]) for a in rsa.inputs["logical"]["characters"] if a["appearance_id"] is not None}
            if {(r.character_id,r.appearance_id) for r in receipts} != expected:
                raise HTTPException(409,"SHOT_USAGE_SET_INCOMPLETE")
            if not receipts:
                plan["skipped"].append({"shotId":shot_id,"status":"NO_APPEARANCE_DEMAND"})
        except HTTPException as exc:
            plan["blocked"].append({"shotId":shot_id,"code":str(exc.detail)});continue
        for receipt in receipts:
            try:
                verify_usage(db, receipt.id, receipt.appearance_id)
                asset = db.get(CharacterAppearance, receipt.appearance_id)
                if not asset or asset.novel_id != novel_id or asset.character_id != receipt.character_id:
                    raise HTTPException(409, "APPEARANCE_SCOPE_MISMATCH")
                if asset.status == "READY":
                    ready_revision(db, asset, load_prompt()["definition"])
                if asset.status not in {"NEEDS_GENERATION", "FAILED"}:
                    plan["skipped"].append({"appearanceId": asset.id, "status": asset.status}); continue
                plan["eligible"].setdefault(asset.id, []).append(receipt.id)
            except HTTPException as exc:
                plan["blocked"].append({"shotId": shot_id, "code": str(exc.detail)})
    return plan
