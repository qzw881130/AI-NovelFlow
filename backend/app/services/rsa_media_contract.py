"""Frozen image intent, parent lineage and pure prompt/manifest checks."""
from copy import deepcopy
from collections import defaultdict
from io import BytesIO
import json
import hashlib
import base64
from pathlib import Path
import re
from PIL import Image, ImageDraw
from fastapi import HTTPException
from app.models.rsa_media import RsaImageAttempt as Attempt, RsaMediaArtifact as Artifact
from app.models.resolved_shot_assets import ShotAssetHead, ResolvedImageVersion, ResolvedShotAssets
from app.models.shot import Shot
from app.models.llm_log import LLMLog
from app.services import appearance_image_contract as files
from app.services.resolved_shot_assets_service import require_frozen_rsa
from app.services.resolved_asset_images import IMAGE_POLICY, verify_image_version
from app.services.chapter_asset_parse_service import digest
from app.services.keyframe_reference_contract import snapshot_target, target_semantics, validate_reference_prompt
from app.utils.image_utils import load_chinese_font
from app.services.llm.multimodal import CONTRACT as PROMPT_LOG_CONTRACT, verify_logged_request, MultimodalInputError

VERSION="rsa-media-v1"
POLICY_PATH=Path(__file__).resolve().parents[2]/"prompt_templates/rsa_media_prompt_contract.json"


class ValidationMemo:
    """One validate_video_binding invocation; never shared or persisted."""

    def __init__(self):
        self._caches = defaultdict(dict)
        self._metrics = defaultdict(lambda: {"requests": 0, "real_executions": 0, "cache_hits": 0})
        self._files = {}
        for name in ("image_bytes","inspect_image","compose_sheet","validate_manifest",
                     "artifact_proof","verify_prompt_record","verify_image_version"):
            self._metrics[name]

    @staticmethod
    def fingerprint(value):
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    def lookup(self, name, key):
        metric = self._metrics[name]
        metric["requests"] += 1
        if key in self._caches[name]:
            metric["cache_hits"] += 1
            return True, self._caches[name][key]
        metric["real_executions"] += 1
        return False, None

    def store(self, name, key, value):
        self._caches[name][key] = value

    def observe_file(self, url, signature):
        if url:
            self._files[url] = deepcopy(signature)

    def file_dependencies(self):
        return deepcopy(dict(sorted(self._files.items())))

    def report(self):
        return {name: dict(values) for name, values in sorted(self._metrics.items())}


def _manifest_file_states(inputs, manifest):
    urls = []
    for item in manifest if isinstance(manifest, list) else []:
        image = item.get("image") if isinstance(item, dict) else None
        if isinstance(image, dict) and image.get("url"):
            urls.append(image["url"])
    planned_manifest = inputs.get("manifest") if isinstance(inputs, dict) else None
    for item in planned_manifest if isinstance(planned_manifest, list) else []:
        if not isinstance(item, dict):
            continue
        image = item.get("image")
        if isinstance(image, dict) and image.get("url"):
            urls.append(image["url"])
        for reference in item.get("references") if isinstance(item.get("references"), list) else []:
            if isinstance(reference, dict) and reference.get("url"):
                urls.append(reference["url"])
    return [(url, files.image_source_signature(url)) for url in sorted(set(urls))]


def _artifact_dependency_state(db, artifact_id, trail=None):
    trail = set() if trail is None else set(trail)
    if artifact_id in trail:
        return {"cycle": artifact_id}
    trail.add(artifact_id)
    row = db.get(Artifact, artifact_id)
    attempt = db.get(Attempt, row.task_id) if row else None
    data = row.data if row and isinstance(row.data, dict) else {}
    execution = attempt.execution if attempt and isinstance(attempt.execution, dict) else {}
    prompt = execution.get("prompt") if isinstance(execution.get("prompt"), dict) else {}
    log = db.get(LLMLog, prompt.get("llm_log_id")) if prompt.get("llm_log_id") else None
    parents = []
    for parent in data.get("parents") if isinstance(data.get("parents"), list) else []:
        if not isinstance(parent, dict):
            parents.append(parent)
        elif parent.get("kind") == "ARTIFACT":
            parents.append(_artifact_dependency_state(db, parent.get("id"), trail))
        else:
            reference = parent.get("reference") if isinstance(parent.get("reference"), dict) else {}
            version = db.get(ResolvedImageVersion, reference.get("image_revision_id")) if reference.get("image_revision_id") else None
            version_data = version.data if version and isinstance(version.data, dict) else {}
            parents.append({
                "reference": reference,
                "version": ({"id": version.id, "seal": version.seal, "origin_hash": version.origin_hash,
                             "data_hash": digest(version_data)} if version else None),
                "source": files.image_source_signature((version_data.get("snapshot") or {}).get("url")),
            })
    return {
        "artifact": ({"id": row.id, "seal": row.seal, "stage": row.stage, "frame_index": row.frame_index,
                      "shot_id": row.shot_id, "rsa_id": row.rsa_id, "data_hash": digest(data),
                      "source": files.image_source_signature((data.get("image") or {}).get("url"))} if row else None),
        "attempt": ({"id": attempt.id, "status": attempt.status, "artifact_id": attempt.artifact_id,
                     "input_hash": attempt.input_hash, "inputs_hash": digest(attempt.inputs),
                     "execution_hash": digest(attempt.execution)} if attempt else None),
        "llm_log": ({key:getattr(log,key) for key in (
            "id","status","response","system_prompt","user_prompt","novel_id","chapter_id",
            "task_type","provider","model","request_info",
        )} if log else None),
        "parents": parents,
    }


def policy():
    raw=POLICY_PATH.read_text(encoding="utf-8");data=json.loads(raw)
    if any(not isinstance(data.get(k),str) or not data[k].strip() for k in ("version","system_suffix","user_template")):
        raise ValueError("RSA_MEDIA_PROMPT_POLICY_INVALID")
    return {"file":"prompt_templates/rsa_media_prompt_contract.json","hash":digest(raw),"definition":data}


def pin_rsa(db,shot_id,rsa_id=None,rsa_hash=None,memo=None):
    if (rsa_id is None)!=(rsa_hash is None):raise HTTPException(409,"RSA_PIN_INCOMPLETE")
    if rsa_id is None:
        head=db.get(ShotAssetHead,shot_id)
        row=db.get(ResolvedShotAssets,head.rsa_id) if head and head.rsa_id else None
        if not row:raise HTTPException(409,"RSA_REQUIRED")
        rsa_id,rsa_hash=row.id,row.result_hash
    return require_frozen_rsa(db,shot_id,rsa_id,rsa_hash,memo=memo)


def artifact_proof(db,artifact_id,*,rsa_id,rsa_hash,seen=None,memo=None):
    seen=set() if seen is None else seen
    if artifact_id in seen or len(seen)>256:raise HTTPException(409,"RSA_LINEAGE_CYCLE")
    seen.add(artifact_id)
    row=db.get(Artifact,artifact_id)
    attempt=db.get(Attempt,row.task_id) if row else None
    cache_key = memo.fingerprint({
        "artifact_id": artifact_id, "rsa_id": rsa_id, "rsa_hash": rsa_hash,
        "dependencies": _artifact_dependency_state(db, artifact_id),
    }) if memo else None
    if memo:
        hit, cached = memo.lookup("artifact_proof", cache_key)
        if hit:
            return cached
    if (not row or row.rsa_id!=rsa_id or row.seal!=digest(row.data) or row.data.get("rsa_hash")!=rsa_hash
            or row.data.get("rsa_id")!=rsa_id or row.data.get("id")!=row.id or row.data.get("shot_id")!=row.shot_id
            or not attempt or attempt.status!="SUCCEEDED" or attempt.artifact_id!=row.id
            or row.stage!=attempt.stage or row.frame_index!=attempt.frame_index or row.shot_id!=attempt.shot_id
            or attempt.rsa_id!=rsa_id or attempt.rsa_hash!=rsa_hash or digest(attempt.inputs)!=attempt.input_hash
            or row.data.get("input_hash")!=attempt.input_hash or row.data.get("receipt")!=attempt.execution.get("receipt")):
        raise HTTPException(409,"RSA_LINEAGE_UNVERIFIED_OR_MISMATCH")
    rsa=require_frozen_rsa(db,row.shot_id,rsa_id,rsa_hash,memo=memo)
    validate_inputs_rsa(db,attempt.inputs,rsa,memo=memo)
    validate_manifest(attempt.inputs,row.data['manifest'],memo=memo)
    verify_prompt_record(db,attempt.inputs,attempt.execution['prompt'],memo=memo)
    from app.services.rsa_media_graph import inspect_graph
    execution=attempt.execution;graph=execution['graph'];uploads=execution['uploads']
    inspection=inspect_graph(graph,attempt.inputs['workflow']['mapping'],attempt.inputs['workflow']['reference_nodes'],
        filenames=[u['filename'] for u in uploads],prompt=execution['prompt']['text'])
    if (digest(graph)!=execution['submit']['graph_hash'] or inspection!=execution['graph_proof']
            or row.data['receipt']['prompt_id']!=execution['submit']['prompt_id']
            or row.data['receipt']['semantic_graph_hash']!=inspection['semantic_graph_hash']
            or len(uploads)!=len(row.data['manifest'])):
        raise HTTPException(409,'RSA_LINEAGE_SUBMISSION_CHANGED')
    for upload,reference in zip(uploads,row.data['manifest']):
        if (upload['payload_sha256']!=reference['image']['sha256'] or upload['remote_sha256']!=reference['image']['sha256']
                or upload['manifest_hash']!=digest(reference)):
            raise HTTPException(409,'RSA_LINEAGE_UPLOAD_CHANGED')
    _,info=files.image_bytes(row.data["image"]["url"],IMAGE_POLICY,memo=memo)
    if info!=row.data["image"] or info["sha256"]!=row.data["receipt"].get("remote_sha256"):
        raise HTTPException(409,"RSA_DERIVED_IMAGE_BYTES_CHANGED")
    if row.data.get("manifest")!=attempt.execution.get("manifest") or row.data.get("parents")!=attempt.inputs.get("parents"):
        raise HTTPException(409,"RSA_LINEAGE_PARENT_CHANGED")
    for parent in row.data["parents"]:
        if parent["kind"]=="ARTIFACT":
            ancestor=artifact_proof(db,parent["id"],rsa_id=rsa_id,rsa_hash=rsa_hash,seen=seen,memo=memo)
            if ancestor.seal!=parent["seal"]:raise HTTPException(409,"RSA_LINEAGE_PARENT_CHANGED")
        else:
            verify_image_version(db,parent["reference"],memo=memo)
    if memo:
        memo.store("artifact_proof", cache_key, row)
    return row


def current_primary(db,shot,memo=None):
    if shot.image_status!="completed" or not shot.image_task_id or not shot.image_url:
        raise HTTPException(409,"PRIMARY_RSA_IMAGE_REQUIRED")
    attempt=db.get(Attempt,shot.image_task_id)
    artifact=db.get(Artifact,attempt.artifact_id) if attempt and attempt.artifact_id else None
    if (not artifact or artifact.stage!="SHOT" or artifact.shot_id!=shot.id or artifact.data["image"]["url"]!=shot.image_url):
        raise HTTPException(409,"PRIMARY_IMAGE_LINEAGE_REQUIRED")
    artifact_proof(db,artifact.id,rsa_id=artifact.rsa_id,rsa_hash=artifact.data["rsa_hash"],memo=memo)
    return artifact


def keyframe_parent(db,shot,index,target,primary,memo=None):
    intent=target["reference_intent"]
    if intent["mode"]=="none":raise HTTPException(409,"KEYFRAME_RSA_LINEAGE_REFERENCE_REQUIRED")
    frames=json.loads(shot.keyframes or '[]')
    previous=frames[index-1] if index else None
    selected_url=intent["url"]
    if selected_url==primary.data["image"]["url"] or (not selected_url and index==0):
        return primary,"PRIMARY_STORYBOARD"
    if not previous or (selected_url and selected_url!=previous.get("image_url")):
        raise HTTPException(409,"CUSTOM_REFERENCE_LINEAGE_REQUIRED")
    if previous.get("image_status") not in {None,"completed"} or not previous.get("image_task_id"):
        raise HTTPException(409,"PREVIOUS_KEYFRAME_NOT_READY")
    attempt=db.get(Attempt,previous["image_task_id"])
    artifact=db.get(Artifact,attempt.artifact_id) if attempt and attempt.artifact_id else None
    if (not artifact or artifact.stage!="KEYFRAME" or artifact.shot_id!=shot.id or artifact.frame_index!=index-1
            or artifact.data["image"]["url"]!=previous.get("image_url")):
        raise HTTPException(409,"PREVIOUS_KEYFRAME_LINEAGE_REQUIRED")
    artifact_proof(db,artifact.id,rsa_id=primary.rsa_id,rsa_hash=primary.data["rsa_hash"],memo=memo)
    produced=attempt.inputs["target"]["current_state"]
    if produced!=target["previous_state_text"]:
        raise HTTPException(409,"PREVIOUS_KEYFRAME_STATE_CHANGED")
    return artifact,"PREVIOUS_KEYFRAME"


def planned_manifest(rsa,stage,parent=None,source_kind=None):
    if stage=="KEYFRAME":
        return [{"picture_index":1,"type":source_kind,"artifact_id":parent.id,"artifact_seal":parent.seal,"image":deepcopy(parent.data["image"]),
                 "rsa_id":rsa.id,"rsa_hash":rsa.result_hash}]
    result=[]
    def entry(kind,members,refs):
        result.append({"picture_index":len(result)+1,"type":kind,"members":members,"references":deepcopy(refs),"rsa_id":rsa.id,"rsa_hash":rsa.result_hash})
    if rsa.data["characters"]:
        entry("MERGED_CHARACTER",[{"character_id":c["character_id"],"appearance_id":c["appearance_id"],"name":c["name"],"image_revision_id":c["reference_image_id"]} for c in rsa.data["characters"]],
              [c["image"] for c in rsa.data["characters"]])
    scene=rsa.data["scene"];entry("SCENE",[{"scene_id":scene["scene_id"],"name":scene["name"],"image_revision_id":scene["reference_image_id"]}],[scene["image"]])
    if rsa.data["props"]:
        entry("MERGED_PROP",[{"prop_id":p["prop_id"],"name":p["name"],"image_revision_id":p["reference_image_id"]} for p in rsa.data["props"]],[p["image"] for p in rsa.data["props"]])
    return result


def validate_inputs_rsa(db,inputs,rsa,memo=None):
    if inputs['context']['resolved_assets']!=rsa.data or inputs['context']['logical_assets']!=rsa.inputs['logical']:
        raise HTTPException(409,'RSA_LINEAGE_BUSINESS_SNAPSHOT_CHANGED')
    parent,kind=None,None
    if inputs['stage']=='KEYFRAME':
        if len(inputs['parents'])!=1 or inputs['parents'][0]['kind']!='ARTIFACT':raise HTTPException(409,'RSA_PARENT_SET_CHANGED')
        parent=db.get(Artifact,inputs['parents'][0]['id'])
        if not parent or parent.rsa_id!=rsa.id or parent.data['rsa_hash']!=rsa.result_hash:raise HTTPException(409,'RSA_PARENT_MANIFEST_CONFLICT')
        kind='PRIMARY_STORYBOARD' if parent.stage=='SHOT' else 'PREVIOUS_KEYFRAME'
    expected=planned_manifest(rsa,inputs['stage'],parent,kind)
    parents=([{'kind':'ARTIFACT','id':parent.id,'seal':parent.seal}] if parent else
             [{'kind':'IMAGE_VERSION','reference':deepcopy(r)} for m in expected for r in m['references']])
    if inputs['manifest']!=expected or inputs['parents']!=parents:raise HTTPException(409,'RSA_REFERENCE_MANIFEST_CONFLICT')


def artifact_dir(novel_id,task_id):
    root=files.file_storage.base_dir.resolve()
    path=(root/f"story_{novel_id[:8]}"/"rsa_media"/task_id).resolve()
    if not path.is_relative_to(root):raise ValueError("RSA_MEDIA_PATH_INVALID")
    path.mkdir(parents=True,exist_ok=True)
    return path


def compose_sheet(originals,members,memo=None):
    cache_key = memo.fingerprint({
        "inputs": [{"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)} for raw in originals],
        "members": members,
    }) if memo else None
    if memo:
        hit, cached = memo.lookup("compose_sheet", cache_key)
        if hit:
            return cached[0], deepcopy(cached[1])
    rendered=[]
    for raw in originals:
        with Image.open(BytesIO(raw)) as image:
            image.load();copy=image.convert("RGB");copy.thumbnail((1400,1000));rendered.append(copy)
    width=max(im.width for im in rendered)+30;height=sum(im.height+48 for im in rendered)+30
    if width*height>IMAGE_POLICY["max_source_pixels"]:raise ValueError("REFERENCE_MERGE_PIXEL_BUDGET")
    canvas=Image.new("RGB",(width,height),"white");draw=ImageDraw.Draw(canvas);font=load_chinese_font(22)
    y=15;tiles=[]
    for member,image in zip(members,rendered):
        draw.text((15,y),member["name"],fill="black",font=font);canvas.paste(image,(15,y+36))
        tiles.append({"image_revision_id":member["image_revision_id"],"name":member["name"],"box":[15,y+36,15+image.width,y+36+image.height]});y+=image.height+48
    buffer=BytesIO();canvas.save(buffer,format="PNG");payload=buffer.getvalue()
    for image in rendered:image.close()
    canvas.close()
    composition={"method":"LABELLED_VERTICAL_SHEET_V1","tiles":tiles}
    if memo:
        memo.store("compose_sheet",cache_key,(payload,deepcopy(composition)))
    return payload,composition


def build_reference_files(db,inputs,task_id,memo=None):
    result=[]
    for planned in inputs["manifest"]:
        record=deepcopy(planned)
        if "artifact_id" in planned:
            parent=artifact_proof(db,planned["artifact_id"],rsa_id=inputs["rsa_id"],rsa_hash=inputs["rsa_hash"],memo=memo)
            payload,info=files.image_bytes(parent.data["image"]["url"],IMAGE_POLICY,memo=memo)
            record["composition"]={"method":"COPY_DERIVED_V1","artifact_id":parent.id}
        else:
            originals=[]
            for ref in planned["references"]:
                verify_image_version(db,ref,memo=memo)
                originals.append(files.image_bytes(ref["url"],IMAGE_POLICY,memo=memo)[0])
            if len(originals)==1:
                payload=originals[0];record["composition"]={"method":"IDENTITY_COPY_V1"}
            else:
                payload,record["composition"]=compose_sheet(originals,planned["members"],memo=memo)
            info=files.inspect_image(payload,IMAGE_POLICY,memo=memo)
        extension={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}[info['format']]
        destination=artifact_dir(inputs["novel_id"],task_id)/f"reference-{planned['picture_index']}{extension}"
        with destination.open("xb") as out:out.write(payload)
        _,image=files.image_bytes(files.local_path_to_url(str(destination)),IMAGE_POLICY,memo=memo)
        record["image"]=image;result.append(record)
    return result


def validate_manifest(inputs,manifest,memo=None):
    cache_key = memo.fingerprint({
        "inputs": inputs, "manifest": manifest, "files": _manifest_file_states(inputs, manifest),
    }) if memo else None
    if memo:
        hit, _ = memo.lookup("validate_manifest", cache_key)
        if hit:
            return
    if len(manifest)!=len(inputs["manifest"]):raise ValueError("RSA_REFERENCE_MANIFEST_CONFLICT")
    for planned,actual in zip(inputs["manifest"],manifest):
        if set(actual)!=set(planned)|{'image','composition'}:raise ValueError('RSA_REFERENCE_MANIFEST_FIELDS_CHANGED')
        if any(actual.get(k)!=v for k,v in planned.items() if k!="image"):
            raise ValueError("RSA_REFERENCE_MANIFEST_CONFLICT")
        _,info=files.image_bytes(actual["image"]["url"],IMAGE_POLICY,memo=memo)
        if info!=actual["image"]:raise ValueError("RSA_REFERENCE_BYTES_CHANGED")
        if "artifact_id" in planned and info["sha256"]!=planned["image"]["sha256"]:
            raise ValueError("RSA_REFERENCE_LINEAGE_BYTES_CHANGED")
        if len(planned.get("references",[]))==1 and info["sha256"]!=planned["references"][0]["sha256"]:
            raise ValueError("RSA_REFERENCE_VERSION_BYTES_CHANGED")
        if len(planned.get('references',[]))>1:
            originals=[files.image_bytes(ref['url'],IMAGE_POLICY,memo=memo)[0] for ref in planned['references']]
            expected,composition=compose_sheet(originals,planned['members'],memo=memo)
            if info['sha256']!=hashlib.sha256(expected).hexdigest() or actual['composition']!=composition:raise ValueError('RSA_REFERENCE_COMPOSITION_CHANGED')
    if memo:
        memo.store("validate_manifest",cache_key,True)


def parse_prompt(raw,count,source_kind=None):
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError("DUPLICATE_PROMPT_JSON_KEY")
            result[k]=v
        return result
    data=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(data,dict) or set(data)!={"status","final_prompt","conflicts"} or not isinstance(data["conflicts"],list):
        raise ValueError("RSA_PROMPT_RESPONSE_INVALID")
    if data["status"]=="ASSET_CONFLICT":
        if data["final_prompt"] is not None or not data["conflicts"]:raise ValueError("RSA_CONFLICT_RESPONSE_INVALID")
        raise ValueError("UPSTREAM_ASSET_CONFLICT: "+json.dumps(data["conflicts"],ensure_ascii=False))
    prompt=data["final_prompt"]
    if data["status"]!="READY" or data["conflicts"] or not isinstance(prompt,str) or not prompt.strip():raise ValueError("RSA_PROMPT_NOT_READY")
    indexes=set(int(n) for n in re.findall(r"<Picture\s+(\d+)>",prompt,flags=re.I))
    if indexes!=set(range(1,count+1)) and not (source_kind and count==1 and not indexes):
        raise ValueError("RSA_PROMPT_PICTURE_MANIFEST_MISMATCH")
    if source_kind:validate_reference_prompt(prompt,source_kind)
    return prompt


def verify_prompt_record(db,inputs,record,memo=None):
    log=db.get(LLMLog,record.get('llm_log_id')) if record.get('llm_log_id') else None
    payload=record.get('payload') or {}
    reference_manifest=payload.get('reference_image_manifest') if isinstance(payload,dict) else None
    cache_key = memo.fingerprint({
        "inputs": inputs, "record": record,
        "log": ({key:getattr(log,key) for key in (
            "id","status","response","system_prompt","user_prompt","novel_id","chapter_id",
            "task_type","provider","model","request_info",
        )} if log else None),
        "files": _manifest_file_states(inputs, reference_manifest),
    }) if memo else None
    if memo:
        hit, _ = memo.lookup("verify_prompt_record", cache_key)
        if hit:
            return
    if (not record.get('validated') or record.get('cache_key')!=inputs['prompt_cache_key']
            or not log or log.status!='success' or log.response!=record.get('raw_response')
            or log.system_prompt!=inputs['template']['text'] or log.system_prompt!=record.get('system_prompt') or log.user_prompt!=record.get('logged_user_prompt')
            or log.novel_id!=inputs['novel_id'] or log.chapter_id!=inputs['chapter_id']
            or log.task_type!=('shot_image_prompt' if inputs['stage']=='SHOT' else 'keyframe_image_prompt')):
        raise HTTPException(409,'RSA_PROMPT_PROVENANCE_CHANGED')
    if (payload.get('rsa_id')!=inputs['rsa_id'] or payload.get('rsa_hash')!=inputs['rsa_hash']
            or any(payload.get(k)!=v for k,v in inputs['context'].items())):
        raise HTTPException(409,'RSA_PROMPT_BUSINESS_INPUT_CHANGED')
    validate_manifest(inputs,payload['reference_image_manifest'],memo=memo)
    expected=inputs['policy']['definition']['user_template'].format_map({'payload':json.dumps(payload,ensure_ascii=False)})
    logged=json.loads(log.user_prompt)
    if not isinstance(logged,list) or len(logged)!=len(inputs['manifest'])+1 or logged[0]!={'type':'text','text':expected}:
        raise HTTPException(409,'RSA_PROMPT_INPUT_LOG_CHANGED')
    # New attempts pin the image-log contract in immutable inputs. Reused legacy
    # prompts retain their original contract; no historical Log/Source is rewritten.
    log_contract=inputs.get('prompt_log_contract')
    if log_contract or record.get('input_log_contract'):
        if log_contract!=PROMPT_LOG_CONTRACT or record.get('input_log_contract')!=log_contract:
            raise HTTPException(409,'RSA_PROMPT_LOG_CONTRACT_CHANGED')
        content=[{'type':'text','text':expected}]
        for reference in payload['reference_image_manifest']:
            raw,info=files.image_bytes(reference['image']['url'],IMAGE_POLICY,memo=memo)
            mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}[info['format']]
            content.append({'type':'image_url','image_url':{'url':f'data:{mime};base64,'+base64.b64encode(raw).decode()}})
        try:
            verify_logged_request(log,content)
            if record.get('request_info_hash')!=digest(json.loads(log.request_info)):
                raise MultimodalInputError('MULTIMODAL_REQUEST_INFO_CHANGED')
        except MultimodalInputError as exc:
            raise HTTPException(409,'RSA_PROMPT_MULTIMODAL_PROOF_CHANGED: '+str(exc)) from exc
    source_kind=inputs['manifest'][0]['type'] if inputs['stage']=='KEYFRAME' else None
    if parse_prompt(log.response,len(inputs['manifest']),source_kind)!=record['text']:
        raise HTTPException(409,'RSA_PROMPT_TEXT_CHANGED')
    if memo:
        memo.store("verify_prompt_record",cache_key,True)
