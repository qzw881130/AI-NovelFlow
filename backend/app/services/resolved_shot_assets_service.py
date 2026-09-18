"""The sole persistent Shot asset resolver. Reads validate a frozen object; only explicit resolution creates versions."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.models.shot import Shot
from app.models.novel import Chapter
from app.models.task import Task
from app.models.resolved_shot_assets import ResolvedShotAssets as RSA, ShotAssetHead as Head, ShotAppearanceDemand as Demand
from app.services.chapter_asset_parse_service import digest
from app.services.chapter_shot_split_service import snapshot, source_payload
from app.models.chapter_shot_split import ShotSource
from app.services.shot_asset_logic import collect_logical_assets, validate_logical_dependencies, image_slots
from app.services.resolved_asset_images import IMAGE_POLICY, observe_image, freeze_image, verify_image_version

VERSION = "resolved-shot-assets-v1"
TASK_TYPE = "shot_asset_resolution"


def rsa_seal(row):
    return digest({"id":row.id,"shot_id":row.shot_id,"novel_id":row.novel_id,"chapter_id":row.chapter_id,
        "task_id":row.task_id,"revision":row.revision,"version":row.resolver_version,"status":row.status,
        "input_hash":row.input_hash,"result_hash":row.result_hash})


def demand_payload(row):
    return {key:getattr(row,key) for key in ("id","rsa_id","novel_id","chapter_id","shot_id","character_id","appearance_id","logical_hash","proof")}


def observe_all(db, logic, memo=None):
    observations, payloads = {}, {}
    total = 0
    for slot, kind, asset_id in image_slots(logic):
        value, data = observe_image(db,logic["novel_id"],kind,asset_id,memo=memo)
        total += len(data or b"")
        if total > 268435456:
            raise HTTPException(409,"RSA_IMAGE_BYTE_BUDGET_EXCEEDED")
        observations[slot], payloads[slot] = value, data
    return observations, payloads


def materialize(logic, observations, references):
    if logic is None:
        return {"logical_ready":False,"logical_hash":None,"characters":[],"scene":None,"props":[]}
    def image_fields(slot):
        ref = references.get(slot)
        return {"image_status":"READY" if observations[slot]["ready"] else "BLOCKED",
            "reference_image_id":ref["image_revision_id"] if ref else None,"image":deepcopy(ref)}
    return {"logical_ready":True,"logical_hash":digest(logic),
        "characters":[{"character_id":c["character_id"],"name":c["definition"]["name"],"binding_id":c["binding"]["id"],
            "entity_type":c["definition"]["entity_type"],"group_size_hint":c["definition"]["group_size_hint"],
            "appearance_id":c["appearance_id"],"selection":deepcopy(c["selection"]),
            **image_fields("character:"+c["character_id"])} for c in logic["characters"]],
        "scene":{"scene_id":logic["scene"]["scene_id"],"name":logic["scene"]["definition"]["name"],
            "binding_id":logic["scene"]["binding"]["id"],**image_fields("scene")},
        "props":[{"prop_id":p["prop_id"],"name":p["definition"]["name"],"binding_id":p["binding"]["id"],
            **image_fields("prop:"+p["prop_id"])} for p in logic["props"]]}


def blockers_for(inputs):
    if not inputs.get("logical"):
        return [{"slot":"source","code":"NEEDS_REBUILD","detail":inputs.get("source_error")}]
    return [{"slot":slot,"code":value["issue"],"asset_id":value["origin"]["asset_id"]}
            for slot,value in inputs["images"].items() if not value["ready"]]


def check_envelope(db, row):
    if (not row or row.resolver_version != VERSION or row.status not in {"READY","BLOCKED"}
            or digest(row.inputs) != row.input_hash or digest(row.data) != row.result_hash or rsa_seal(row) != row.seal):
        raise HTTPException(409,"RSA_ENVELOPE_INVALID")
    task = db.get(Task,row.task_id)
    meta = json.loads(task.metadata_json or "{}") if task else {}
    if (not task or task.type != TASK_TYPE or task.status != "completed" or task.shot_id != row.shot_id
            or task.novel_id != row.novel_id or task.chapter_id != row.chapter_id or meta.get("rsa_id") != row.id
            or meta.get("rsa_hash") != row.result_hash or meta.get("rsa_seal") != row.seal or meta.get("execution_purpose") != "production"):
        raise HTTPException(409,"RSA_TASK_PROOF_INVALID")
    logic = row.inputs.get("logical")
    if logic and (logic["shot_id"] != row.shot_id or logic["novel_id"] != row.novel_id or logic["chapter_id"] != row.chapter_id):
        raise HTTPException(409,"RSA_OWNER_MISMATCH")
    expected = materialize(logic,row.inputs["images"],row.data["references"])
    if any(row.data.get(key) != value for key,value in expected.items()) or row.data["blockers"] != blockers_for(row.inputs):
        raise HTTPException(409,"RSA_MATERIALIZED_ASSETS_CHANGED")
    if row.status != ("BLOCKED" if row.data["blockers"] else "READY"):
        raise HTTPException(409,"RSA_STATUS_MISMATCH")
    if logic:
        slots = {slot:(kind,aid) for slot,kind,aid in image_slots(logic)}
        if set(slots) != set(row.inputs["images"]):
            raise HTTPException(409,"RSA_IMAGE_SLOT_SET_CHANGED")
        for slot,(kind,aid) in slots.items():
            observation = row.inputs["images"][slot]
            if observation["origin"]["kind"] != kind or observation["origin"]["asset_id"] != aid or observation["origin"]["novel_id"] != row.novel_id:
                raise HTTPException(409,"RSA_IMAGE_OWNER_CHANGED")
        if set(row.data["references"]) != {slot for slot,value in row.inputs["images"].items() if value["ready"]}:
            raise HTTPException(409,"RSA_REFERENCE_SET_CHANGED")
        for slot,ref in row.data["references"].items():
            if ref["version"]["origin"] != row.inputs["images"][slot]["origin"]:
                raise HTTPException(409,"RSA_REFERENCE_ORIGIN_CHANGED")
    return row


def check_logical_rsa(db, row):
    check_envelope(db,row)
    if not row.data["logical_ready"]:
        raise HTTPException(409,"RSA_LOGICAL_SOURCE_NOT_READY")
    from app.services.chapter_governance import require_source
    require_source(db,row.shot_id)
    validate_logical_dependencies(db,row.inputs["logical"])
    return row


def validate_frozen_rsa(db, row, *, require_ready=True, memo=None):
    """Consumer contract: exact RSA, exact current head, exact frozen images. No new choices or versions."""
    check_logical_rsa(db,row)
    head = db.get(Head,row.shot_id)
    if not head or head.rsa_id != row.id or head.revision != row.revision:
        raise HTTPException(409,"RSA_SUPERSEDED")
    observations, _ = observe_all(db,row.inputs["logical"],memo=memo)
    if observations != row.inputs["images"]:
        raise HTTPException(409,"RSA_UPSTREAM_IMAGE_VERSION_CHANGED")
    for ref in row.data["references"].values():
        verify_image_version(db,ref,memo=memo)
    if require_ready and row.status != "READY":
        raise HTTPException(409,{"code":"RSA_BLOCKED","blockers":row.data["blockers"]})
    return row


def require_frozen_rsa(db, shot_id, rsa_id, expected_hash, memo=None):
    row = db.get(RSA,rsa_id)
    if not row or row.shot_id != shot_id or not expected_hash or row.result_hash != expected_hash:
        raise HTTPException(409,"RSA_MANIFEST_CONFLICT")
    return validate_frozen_rsa(db,row,memo=memo)


def expire_rsa_task(db, task, *, commit=True):
    row = db.query(RSA).filter_by(task_id=task.id).first()
    if row and row.status == "RUNNING" and (task.status not in {"pending","running"} or row.expires_at < datetime.utcnow()):
        row.status, row.data, row.completed_at = "FAILED", {"blockers":[{"code":"RSA_EXECUTION_INTERRUPTED"}]}, datetime.utcnow()
        row.input_hash, row.result_hash = digest(row.inputs),digest(row.data)
        row.seal = rsa_seal(row)
        if task.status in {"pending","running"}:
            task.status, task.error_message, task.completed_at = "failed","RSA_EXECUTION_INTERRUPTED",datetime.utcnow()
        if commit: db.commit()
        return True
    if not row and task.status in {"pending","running"}:
        task.status, task.error_message = "failed","RSA_RECORD_MISSING"
        if commit: db.commit()
        return True
    return False


def rsa_response(db, row):
    state, issue = row.status, None
    try:
        if row.status in {"READY","BLOCKED"}:
            check_envelope(db,row)
            head = db.get(Head,row.shot_id)
            if not head or head.rsa_id != row.id:
                raise HTTPException(409,"RSA_SUPERSEDED")
            if row.data["logical_ready"]:
                validate_frozen_rsa(db,row,require_ready=False)
    except (HTTPException,ValueError,KeyError,TypeError,OSError) as exc:
        state,issue = "STALE", exc.detail if isinstance(exc,HTTPException) else str(exc)
    return {"id":row.id,"shotId":row.shot_id,"taskId":row.task_id,"revision":row.revision,"resolverVersion":row.resolver_version,
        "status":row.status,"effectiveStatus":state,"ready":state=="READY","issue":issue,"inputHash":row.input_hash,
        "resultHash":row.result_hash,"seal":row.seal,"createdAt":row.created_at,"assets":row.data}


def current_rsa(db, shot_id):
    shot = db.get(Shot,shot_id)
    if not shot: raise HTTPException(404,"分镜不存在")
    head = db.get(Head,shot_id)
    row = db.get(RSA,head.rsa_id) if head and head.rsa_id else None
    if row: return rsa_response(db,row)
    return {"id":None,"shotId":shot_id,"status":"NOT_RESOLVED","effectiveStatus":"NOT_RESOLVED","ready":False,
        "issue":"RSA_REQUIRED" if shot.source_record else "LEGACY_SHOT_NEEDS_REBUILD","assets":None}


class ResolvedShotAssetsService:
    def __init__(self, db): self.db = db

    def _capture_inputs(self, shot_id):
        try:
            from app.services.chapter_governance import require_source
            require_source(self.db,shot_id)
            logic = collect_logical_assets(self.db,shot_id)
        except (HTTPException,ValueError,KeyError,TypeError) as exc:
            shot, source = self.db.get(Shot,shot_id),self.db.get(ShotSource,shot_id)
            return {"version":VERSION,"logical":None,"images":{},"source_error":exc.detail if isinstance(exc,HTTPException) else str(exc),
                "observed_shot":snapshot(shot) if shot else None,"observed_source":source_payload(source) if source else None}, {}
        observations, payloads = observe_all(self.db,logic)
        return {"version":VERSION,"image_policy":IMAGE_POLICY,"logical":logic,"images":observations,"source_error":None},payloads

    def resolveShotAssets(self, shot_id):
        db = self.db
        shot = db.get(Shot,shot_id)
        if not shot: raise HTTPException(404,"分镜不存在")
        if getattr(shot,'completion_disposition','NORMAL')=='DEGRADED_NARRATION_CARD':
            raise HTTPException(409,'NARRATION_CARD_RSA_FORBIDDEN')
        chapter = db.get(Chapter,shot.chapter_id)
        if not chapter: raise HTTPException(409,"RSA_CHAPTER_MISSING")
        head = db.get(Head,shot_id)
        expected_revision, expected_id = (head.revision,head.rsa_id) if head else (0,None)
        previous = db.get(RSA,head.rsa_id) if head and head.rsa_id else None
        if previous and previous.status == "RUNNING":
            task = db.get(Task,previous.task_id)
            if task: expire_rsa_task(db,task)
            else:
                previous.status,previous.data,previous.completed_at="FAILED",{"blockers":[{"code":"RSA_TASK_MISSING"}]},datetime.utcnow()
                previous.result_hash=digest(previous.data);previous.seal=rsa_seal(previous);db.commit()
            if previous.status == "RUNNING":
                raise HTTPException(409,"RSA_RESOLUTION_RUNNING")
        # Reuse only the latest complete, fully validated result. Never search older READY rows.
        try:
            inputs, payloads = self._capture_inputs(shot_id)
        except Exception as exc:
            inputs,payloads = {"version":VERSION,"logical":None,"images":{},"source_error":str(exc),"execution_error":str(exc)},{}
        if previous and previous.status in {"READY","BLOCKED"} and previous.input_hash == digest(inputs):
            try:
                check_envelope(db,previous)
                if inputs["logical"]: validate_frozen_rsa(db,previous,require_ready=False)
                return {"success":True,"reused":True,"data":rsa_response(db,previous)}
            except (HTTPException,ValueError,KeyError,TypeError,OSError):
                db.rollback()
        if not head:
            head = Head(shot_id=shot_id,revision=0);db.add(head)
            try: db.flush()
            except IntegrityError as exc:
                db.rollback();raise HTTPException(409,"RSA_ADMISSION_CONFLICT") from exc
        old_revision, old_id = expected_revision, expected_id
        rsa_id, task_id, token = str(uuid4()), str(uuid4()), str(uuid4())
        count = db.query(Head).filter_by(shot_id=shot_id,revision=old_revision,rsa_id=old_id).update({"revision":old_revision+1,"rsa_id":rsa_id},synchronize_session=False)
        if count != 1:
            db.rollback();raise HTTPException(409,"RSA_ADMISSION_CONFLICT")
        row = RSA(id=rsa_id,shot_id=shot_id,novel_id=chapter.novel_id,chapter_id=chapter.id,task_id=task_id,revision=old_revision+1,
            resolver_version=VERSION,status="RUNNING",inputs=inputs,input_hash=digest(inputs),expires_at=datetime.utcnow()+timedelta(minutes=5))
        task = Task(id=task_id,name=f"解析分镜资产：Shot {shot.index}",type=TASK_TYPE,status="running",novel_id=chapter.novel_id,
            chapter_id=chapter.id,shot_id=shot_id,claim_token=token,started_at=datetime.utcnow(),heartbeat_at=datetime.utcnow(),
            current_step="校验逻辑来源并冻结资产版本",metadata_json=json.dumps({"execution_purpose":"production","rsa_id":rsa_id}))
        db.add_all([row,task]);db.commit()
        try:
            if inputs.get("execution_error"):
                raise RuntimeError(inputs["execution_error"])
            # Fence DB writers before comparing the preflight observation and persisting captured bytes.
            locked = db.query(Head).filter_by(shot_id=shot_id,rsa_id=rsa_id,revision=row.revision).update({"rsa_id":rsa_id},synchronize_session=False)
            db.expire_all();row,task = db.get(RSA,rsa_id),db.get(Task,task_id)
            if locked != 1 or not row or row.status != "RUNNING" or not task or task.status != "running" or task.claim_token != token:
                raise RuntimeError("RSA_PUBLICATION_FENCED")
            final_inputs, payloads = self._capture_inputs(shot_id)
            if final_inputs != inputs:
                raise RuntimeError("RSA_INPUTS_CHANGED_DURING_RESOLUTION")
            references = {slot:freeze_image(db,observation,payloads[slot]) for slot,observation in inputs["images"].items() if observation["ready"]}
            # Re-read originals after file capture; detect same-URL content replacement during the operation.
            if inputs["logical"] and observe_all(db,inputs["logical"])[0] != inputs["images"]:
                raise RuntimeError("RSA_SOURCE_BYTES_CHANGED_DURING_CAPTURE")
            if (db.query(Task.id).filter_by(id=task_id,status="running",claim_token=token).first() is None
                    or db.query(Head.shot_id).filter_by(shot_id=shot_id,rsa_id=rsa_id,revision=row.revision).first() is None):
                raise RuntimeError("RSA_PUBLICATION_FENCED")
            data = {**materialize(inputs["logical"],inputs["images"],references),"references":references,"blockers":blockers_for(inputs),"demands":[]}
            if inputs["logical"]:
                for actor in inputs["logical"]["characters"]:
                    if actor["appearance_id"] is None: continue
                    demand = Demand(id=str(uuid4()),rsa_id=rsa_id,novel_id=row.novel_id,chapter_id=row.chapter_id,shot_id=shot_id,
                        character_id=actor["character_id"],appearance_id=actor["appearance_id"],logical_hash=data["logical_hash"],
                        proof={"version":VERSION,"source":deepcopy(inputs["logical"]["source"]),"actor":deepcopy(actor)})
                    demand.seal = digest(demand_payload(demand));db.add(demand)
                    data["demands"].append({**demand_payload(demand),"seal":demand.seal})
            row.data, row.status, row.completed_at = data, "BLOCKED" if data["blockers"] else "READY", datetime.utcnow()
            row.result_hash = digest(data);row.seal = rsa_seal(row)
            task.status, task.progress, task.current_step, task.completed_at = "completed",100,"资产解析结果："+row.status,datetime.utcnow()
            task.metadata_json = json.dumps({"execution_purpose":"production","rsa_id":rsa_id,"rsa_hash":row.result_hash,"rsa_seal":row.seal,"rsa_status":row.status})
            db.commit()
            return {"success":True,"reused":False,"data":rsa_response(db,row)}
        except Exception as exc:
            db.rollback();row,task = db.get(RSA,rsa_id),db.get(Task,task_id)
            if row and row.status == "RUNNING":
                row.status, row.data, row.completed_at = "FAILED",{"blockers":[{"code":"RSA_EXECUTION_FAILED","detail":str(exc)}]},datetime.utcnow()
                row.result_hash=digest(row.data);row.seal=rsa_seal(row)
                if task and task.status == "running" and task.claim_token == token:
                    task.status,task.error_message,task.completed_at="failed",str(exc),datetime.utcnow()
                db.commit()
            return {"success":False,"data":rsa_response(db,row),"message":str(exc)}


def resolveShotAssets(shot_id, db):
    return ResolvedShotAssetsService(db).resolveShotAssets(shot_id)
