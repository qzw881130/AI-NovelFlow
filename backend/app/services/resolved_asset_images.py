"""Capture formal asset bytes as immutable versions; never publish back to Book assets."""
from copy import deepcopy
from uuid import uuid4
from fastapi import HTTPException
from app.models.novel import Character, Scene, Prop
from app.models.appearance_timeline import CharacterAppearance
from app.models.task import Task
from app.models.resolved_shot_assets import ResolvedImageVersion
from app.services import appearance_image_contract as image_contract
from app.services.chapter_asset_parse_service import digest

IMAGE_POLICY = {"max_source_bytes": 26214400, "max_source_pixels": 20000000}
MODELS = {"CHARACTER_BASE": Character, "CHARACTER_APPEARANCE": CharacterAppearance, "SCENE": Scene, "PROP": Prop}
OWNER_TASK = {"CHARACTER_BASE": "portrait_task_id", "SCENE": "scene_task_id", "PROP": "prop_task_id"}


def observe_image(db, novel_id, kind, asset_id, memo=None):
    asset = db.get(MODELS[kind],asset_id)
    if not asset or asset.novel_id != novel_id:
        raise HTTPException(409,"RSA_IMAGE_ASSET_SCOPE_MISMATCH")
    descriptor = {"kind":kind,"asset_id":asset_id,"novel_id":novel_id}
    try:
        if kind == "CHARACTER_APPEARANCE":
            descriptor.update(status=asset.status, appearance_image_revision_id=asset.reference_image_revision_id,
                generation_revision=asset.generation_revision, reported_task_id=asset.task_id, definition_hash=asset.definition_hash)
            if asset.status != "READY":
                raise HTTPException(409,"APPEARANCE_"+asset.status)
            data, info = image_contract.ready_revision(db,asset,IMAGE_POLICY,memo=memo)
        else:
            task_id = getattr(asset,OWNER_TASK[kind])
            descriptor.update(status=asset.generating_status, reported_task_id=task_id, source_url=asset.image_url)
            if asset.generating_status not in {None,"completed","ready","READY"}:
                raise HTTPException(409,"FORMAL_IMAGE_"+str(asset.generating_status).upper())
            task = db.get(Task,task_id) if task_id else None
            active = bool(task and task.status in {"pending","queued","running"})
            descriptor["owner_task_active"] = active
            if active:
                raise HTTPException(409,"FORMAL_IMAGE_TASK_ACTIVE")
            data, info = image_contract.image_bytes(asset.image_url,IMAGE_POLICY,memo=memo)
        return {"origin":{**descriptor,"image":info},"ready":True,"issue":None}, data
    except (HTTPException, ValueError, OSError) as exc:
        return {"origin":descriptor,"ready":False,"issue":str(exc.detail if isinstance(exc,HTTPException) else exc)}, None


def verify_image_version(db, reference, memo=None):
    row = db.get(ResolvedImageVersion,reference["image_revision_id"])
    cache_key = memo.fingerprint({
        "reference": reference,
        "row": ({"id": row.id, "seal": row.seal, "origin_hash": row.origin_hash, "data": row.data}
                if row else None),
        "source": image_contract.image_source_signature(
            row.data.get("snapshot", {}).get("url") if row and isinstance(row.data, dict) else None
        ),
    }) if memo else None
    if memo:
        hit, cached = memo.lookup("verify_image_version", cache_key)
        if hit:
            return cached
    if (not row or row.seal != digest(row.data) or reference != reference_for(row) or row.data["id"] != row.id
            or row.origin_hash != digest(row.data["origin"]) or row.novel_id != row.data["origin"]["novel_id"]):
        raise HTTPException(409,"RSA_IMAGE_VERSION_INVALID")
    _, info = image_contract.image_bytes(row.data["snapshot"]["url"],IMAGE_POLICY,memo=memo)
    if info != row.data["snapshot"] or info["sha256"] != row.data["origin"]["image"]["sha256"]:
        raise HTTPException(409,"RSA_FROZEN_IMAGE_BYTES_CHANGED")
    if memo:
        memo.store("verify_image_version", cache_key, row)
    return row


def reference_for(row):
    return {"image_revision_id":row.id,"url":row.data["snapshot"]["url"],"sha256":row.data["snapshot"]["sha256"],
            "version":deepcopy(row.data),"seal":row.seal}


def freeze_image(db, observation, payload):
    origin = observation["origin"]
    fingerprint = digest(origin)
    existing = db.query(ResolvedImageVersion).filter_by(novel_id=origin["novel_id"],origin_hash=fingerprint).order_by(
        ResolvedImageVersion.created_at.desc(),ResolvedImageVersion.id.desc()).first()
    if existing:
        try:
            verify_image_version(db,reference_for(existing))
            return reference_for(existing)
        except (HTTPException, ValueError, OSError):
            pass  # Only an explicit resolution may create a fresh version; never repair the old one in place.
    image_id = str(uuid4())
    extension = {"PNG":".png","JPEG":".jpg","WEBP":".webp"}[origin["image"]["format"]]
    destination = image_contract.file_storage.base_dir / f"story_{origin['novel_id'][:8]}" / "resolved_assets" / "images" / image_id / ("reference"+extension)
    if not destination.resolve().is_relative_to(image_contract.file_storage.base_dir.resolve()):
        raise ValueError("RSA_CAPTURE_PATH_INVALID")
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open("xb") as out:
        out.write(payload)
    url = image_contract.local_path_to_url(str(destination))
    _, info = image_contract.image_bytes(url,IMAGE_POLICY)
    if info["sha256"] != origin["image"]["sha256"]:
        raise ValueError("RSA_CAPTURE_BYTES_MISMATCH")
    data = {"id":image_id,"origin":deepcopy(origin),"snapshot":info,"capture_type":"FORMAL_ASSET_BYTES_V1"}
    row = ResolvedImageVersion(id=image_id,novel_id=origin["novel_id"],origin_hash=fingerprint,data=data,seal=digest(data))
    db.add(row);db.flush()
    return reference_for(row)
