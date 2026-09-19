"""Declarative runtime entry policy plus frozen downstream asset bindings."""
from copy import deepcopy
import json
import os
from time import time
from types import SimpleNamespace
from fastapi import Depends,HTTPException,Request
from app.core.database import get_db
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.rsa_media import RsaImageAttempt,RsaMediaArtifact
from app.services.chapter_governance import require_source,require_rsa,require_primary
from app.services.chapter_asset_parse_service import digest
from app.services.rsa_media_contract import artifact_proof

DEPRECATED={
 'benchmark_generate_shot_image','benchmark_generate_keyframe_image','benchmark_generate_shot_video',
 'generate_transition_video','generate_all_transitions','clear_chapter_resources',
 'upload_shot_image','edit_shot_image','replace_shot_image','edit_keyframe_image','replace_keyframe_image','upload_keyframe_image','upload_keyframe_reference_image',
 'generate_shot_audio','generate_all_shot_audio','upload_dialogue_audio','delete_dialogue_audio','merge_dialogue_audio',
 'update_chapter_resources','create_shot','generate_keyframe_descriptions',
}
SOURCE_ENTRIES={'recommend_video_mode','plan_video_keyframes','save_video_director_plan','patch_video_director_prompt','patch_video_director_keyframe_description',
 'update_shot','batch_update_shots','update_keyframes','set_keyframe_reference_image','set_reference_audio','upload_reference_audio'}
IMAGE_ENTRIES={'generate_shot_image','generate_keyframe_image'}
VIDEO_ENTRIES={'generate_video_director_clip','generate_shot_video','merge_video_director_clips'}
BATCH_ENTRIES={'generate_shot_images_batch','generate_shot_videos_batch','merge_chapter_videos'}
VALIDATED_BINDING_PROOF_VERSION='video-binding-proof-v1'


def _row_snapshot(row):
    return ({column.key:getattr(row,column.key) for column in row.__table__.columns} if row else None)


def _database_token(db):
    connection=db.connection();dialect=connection.dialect.name
    raw=getattr(connection.connection,'dbapi_connection',connection.connection)
    if dialect!='sqlite':
        return {'dialect':dialect,'connectionId':id(raw),'reusable':False}
    value=connection.exec_driver_sql('PRAGMA data_version').scalar_one()
    return {'dialect':'sqlite','connectionId':id(raw),'dataVersion':int(value),'reusable':True}


def _live_asset_state(db,rsa):
    from app.models.appearance_generation import AppearanceGeneration,AppearanceImageRevision
    from app.models.appearance_timeline import AppearanceTimelineRun
    from app.models.asset_resolution import CharacterIdentity,ChapterCharacterBinding,ChapterPropBinding,ChapterSceneBinding
    from app.models.novel import Character
    from app.services.resolved_asset_images import MODELS,OWNER_TASK
    from app.services.shot_asset_logic import image_slots
    result=[];bindings=[];identities=[];timelines=[];logic=rsa.inputs.get('logical') if rsa and isinstance(rsa.inputs,dict) else None
    for slot,kind,asset_id in image_slots(logic) if logic else []:
        asset=db.get(MODELS[kind],asset_id);entry={'slot':slot,'kind':kind,'asset':_row_snapshot(asset)}
        if kind=='CHARACTER_APPEARANCE':
            revision=db.get(AppearanceImageRevision,asset.reference_image_revision_id) if asset and asset.reference_image_revision_id else None
            generation=db.get(AppearanceGeneration,revision.generation_id) if revision else None
            entry.update(revision=_row_snapshot(revision),generation=_row_snapshot(generation))
            run=(db.query(AppearanceTimelineRun).filter_by(novel_id=asset.novel_id,chapter_id=asset.source_chapter_id)
                 .order_by(AppearanceTimelineRun.created_at.desc(),AppearanceTimelineRun.id.desc()).first()) if asset else None
            timelines.append(_row_snapshot(run))
        else:
            task_id=getattr(asset,OWNER_TASK[kind]) if asset else None
            from app.models.task import Task
            entry['ownerTask']=_row_snapshot(db.get(Task,task_id)) if task_id else None
        result.append(entry)
    if logic:
        for item in logic.get('characters',[]):
            identity=db.get(CharacterIdentity,item.get('character_id'));actor=db.get(Character,item.get('character_id'))
            identities.append({'identity':_row_snapshot(identity),'character':_row_snapshot(actor)})
            binding=(item.get('binding') or {}).get('id');bindings.append(_row_snapshot(db.get(ChapterCharacterBinding,binding)) if binding else None)
        scene_binding=((logic.get('scene') or {}).get('binding') or {}).get('id')
        bindings.append(_row_snapshot(db.get(ChapterSceneBinding,scene_binding)) if scene_binding else None)
        for item in logic.get('props',[]):
            binding=(item.get('binding') or {}).get('id');bindings.append(_row_snapshot(db.get(ChapterPropBinding,binding)) if binding else None)
    return {'assets':result,'bindings':bindings,'identities':identities,'appearanceTimelines':timelines}


def _semantic_dependency_fingerprint(snapshot):
    from app.services.rsa_media_contract import ValidationMemo
    return ValidationMemo.fingerprint({key:value for key,value in snapshot.items()
        if key not in {'database','processId'}})


def binding_dependency_snapshot(db,task,binding,file_dependencies):
    from app.models.resolved_shot_assets import ResolvedShotAssets,ShotAssetHead
    from app.models.task import Task
    from app.services import appearance_image_contract as image_files
    from app.services.rsa_media_contract import _artifact_dependency_state
    rsa=db.get(ResolvedShotAssets,binding.get('rsa_id')) if isinstance(binding,dict) else None
    files={url:image_files.image_source_signature(url) for url in sorted(file_dependencies)}
    return {
        'version':VALIDATED_BINDING_PROOF_VERSION,
        'processId':os.getpid(),
        'database':_database_token(db),
        'bindingFingerprint':digest(binding),
        'sourcePin':source_pin(db,task.shot_id),
        'rsa':_row_snapshot(rsa),
        'rsaHead':_row_snapshot(db.get(ShotAssetHead,task.shot_id)),
        'rsaTask':_row_snapshot(db.get(Task,rsa.task_id)) if rsa else None,
        'liveAssets':_live_asset_state(db,rsa),
        'artifacts':[_artifact_dependency_state(db,item.get('id')) for item in binding.get('images',[])],
        'files':files,
    }


def build_validated_binding_proof(db,task,binding,memo):
    files=memo.file_dependencies();snapshot=binding_dependency_snapshot(db,task,binding,files)
    return {'version':VALIDATED_BINDING_PROOF_VERSION,'validatedAt':time(),
        'bindingFingerprint':snapshot['bindingFingerprint'],'dependencyFingerprint':_semantic_dependency_fingerprint(snapshot),
        'files':files,'database':snapshot['database'],'processId':os.getpid()}


def validated_binding_proof_current(db,task,binding,proof):
    if (not isinstance(proof,dict) or proof.get('version')!=VALIDATED_BINDING_PROOF_VERSION
            or proof.get('processId')!=os.getpid() or proof.get('bindingFingerprint')!=digest(binding)
            or not isinstance(proof.get('files'),dict) or not proof.get('database',{}).get('reusable')):
        return False
    try:snapshot=binding_dependency_snapshot(db,task,binding,proof['files'])
    except Exception:return False
    return (snapshot['database'].get('reusable') is True
            and snapshot['database'].get('dialect')==proof['database'].get('dialect')
            and _semantic_dependency_fingerprint(snapshot)==proof.get('dependencyFingerprint'))


def source_pin(db,shot_id):
    source=require_source(db,shot_id)
    return {'version':'runtime-source-v1','shot_id':shot_id,'split_run_id':source.run_id,'source_hash':source.source_hash,'seal':source.render_seal}


def validate_source_pin(db,shot_id,pin):
    if not isinstance(pin,dict) or source_pin(db,shot_id)!=pin:raise HTTPException(409,'RUNTIME_SOURCE_PIN_CHANGED_OR_MISSING')


def audio_source_pin(db, shot_id):
    source = require_source(db, shot_id)
    return {'version':'runtime-source-v1', 'shot_id':shot_id, 'split_run_id':source.run_id,
            'source_hash':source.source_hash, 'seal':source.audio_seal}


def validate_audio_source_pin(db, shot_id, pin):
    if not isinstance(pin, dict) or audio_source_pin(db, shot_id) != pin:
        raise HTTPException(409, 'AUDIO_SOURCE_PIN_CHANGED_OR_MISSING')


async def enforce_shot_entry(request:Request,db=Depends(get_db)):
    if request.method in {'GET','HEAD','OPTIONS'}:return
    name=request.scope['route'].name
    if name in DEPRECATED:raise HTTPException(410,{'code':'LEGACY_ENTRY_RETIRED','entry':name,'next':'使用显式重建、本章分镜资产、分镜最终资产及AudioDrive入口'})
    body={}
    if 'application/json' in request.headers.get('content-type',''):
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(422,'INVALID_REQUEST_OBJECT')
    if body.get('executionPurpose',body.get('execution_purpose','production'))!='production':
        raise HTTPException(410,'BENCHMARK_RUNTIME_RETIRED')
    p=request.path_params;sid=p.get('shot_id');cid=p.get('chapter_id');nid=p.get('novel_id')
    if cid and not db.query(Chapter.id).filter_by(id=cid,novel_id=nid).first():raise HTTPException(404,'章回不存在')
    shot=db.query(Shot).filter_by(id=sid,chapter_id=cid).first() if sid else None
    if sid and not shot:raise HTTPException(404,'分镜不存在；仅接受稳定Shot ID')
    if shot and getattr(shot,'completion_disposition','NORMAL')=='DEGRADED_NARRATION_CARD':
        raise HTTPException(409,'NARRATION_CARD_VISUAL_RUNTIME_FORBIDDEN')
    if name in SOURCE_ENTRIES and sid:require_source(db,sid)
    elif name in IMAGE_ENTRIES:require_rsa(db,sid)
    elif name in VIDEO_ENTRIES:require_primary(db,sid)
    elif name=='batch_update_shots':
        for item in body.get('shots',[]):
            shot=db.query(Shot).filter_by(id=item.get('id'),chapter_id=cid).first()
            if not shot:raise HTTPException(404,'分镜不存在')
            if getattr(shot,'completion_disposition','NORMAL')=='DEGRADED_NARRATION_CARD':
                raise HTTPException(409,'NARRATION_CARD_IMMUTABLE')
            require_source(db,shot.id)
    elif name in BATCH_ENTRIES:
        ids=body.get('shot_ids')
        if ids is None:ids=[s.id for s in db.query(Shot).filter_by(chapter_id=cid)
            if getattr(s,'completion_disposition','NORMAL')!='DEGRADED_NARRATION_CARD']
        if not isinstance(ids,list) or not ids:raise HTTPException(409,'NO_VERIFIED_SHOTS')
        for key in ids:
            member=db.query(Shot).filter_by(id=key,chapter_id=cid).first()
            if not member:raise HTTPException(404,'分镜不存在')
            if getattr(member,'completion_disposition','NORMAL')=='DEGRADED_NARRATION_CARD':
                raise HTTPException(409,'NARRATION_CARD_VISUAL_RUNTIME_FORBIDDEN')
            # #06 has its own per-Shot READY subset contract; avoid turning one BLOCKED member into a global failure.
            if name not in {'generate_shot_images_batch','generate_shot_videos_batch'}:require_source(db,key)
    elif name!='delete_shot' and name not in SOURCE_ENTRIES:
        raise HTTPException(409,{'code':'RUNTIME_ENTRY_NOT_CLASSIFIED','entry':name})


def frame_artifact(db,shot,frame,rsa,memo=None):
    if frame.get('role')=='START':
        primary=require_primary(db,shot.id,memo=memo)[1]
        if frame.get('image_url') not in {None,primary.data['image']['url']}:
            raise HTTPException(409,'START_FRAME_MUST_USE_PRIMARY')
        return primary
    tid=frame.get('image_task_id');attempt=db.get(RsaImageAttempt,tid) if tid else None
    row=db.get(RsaMediaArtifact,attempt.artifact_id) if attempt and attempt.artifact_id else None
    if not row or row.stage!='KEYFRAME' or row.shot_id!=shot.id or row.data['image']['url']!=frame.get('image_url'):
        raise HTTPException(409,'KEYFRAME_LINEAGE_REQUIRED')
    artifact_proof(db,row.id,rsa_id=rsa.id,rsa_hash=rsa.result_hash,memo=memo)
    from app.services.keyframe_reference_contract import _frame_state
    if attempt.inputs['target']['current_state']!=_frame_state(frame,frame.get('index')):
        raise HTTPException(409,'KEYFRAME_PRODUCER_STATE_CHANGED')
    return row


def verified_plan_images(db,shot,frames,required_indexes=None):
    rsa=require_rsa(db,shot.id);result=[]
    for frame in frames:
        item=deepcopy(frame)
        if required_indexes is not None and item.get('index') not in required_indexes:
            result.append(item)
            continue  # Unconsumed historical plan fields are not video reference inputs.
        if item.get('role')=='START':
            item['image_url']=frame_artifact(db,shot,item,rsa).data['image']['url']
        elif item.get('image_url'):
            frame_artifact(db,shot,item,rsa)
        result.append(item)
    return result


def video_binding(db,shot,mode=None,only_window_index=None,memo=None):
    rsa,primary=require_primary(db,shot.id,memo=memo)
    plan=json.loads(shot.video_director_plan or '{}');mode=mode or plan.get('selected_mode') or 'SINGLE_FRAME'
    if mode not in {'SINGLE_FRAME','FIRST_LAST_FRAME','MULTI_KEYFRAME'}:raise HTTPException(422,'INVALID_VIDEO_MODE')
    selected=[]
    if mode=='FIRST_LAST_FRAME':selected=[f for f in plan.get('keyframes',[]) if f.get('role')=='END']
    elif mode=='MULTI_KEYFRAME':
        windows=plan.get('window_plans') or plan.get('execution_windows') or []
        windows=[w for w in windows if only_window_index is None or w.get('window_index')==only_window_index]
        indexes={i for w in windows for i in w.get('keyframe_indexes',[])}
        selected=[f for f in plan.get('keyframes',[]) if f.get('index') in indexes]
        if not indexes:raise HTTPException(409,'VIDEO_KEYFRAME_PLAN_REQUIRED')
        if len(selected)!=len(indexes) or {f['index'] for f in selected}!=indexes:
            raise HTTPException(409,'VIDEO_KEYFRAME_MEMBERSHIP_CHANGED')
    images=[primary]+[frame_artifact(db,shot,f,rsa,memo=memo) for f in selected]
    if mode=='FIRST_LAST_FRAME' and len(selected)!=1:raise HTTPException(409,'VIDEO_END_FRAME_REQUIRED')
    images=list({image.id:image for image in images}.values())
    body={'version':'runtime-gate-v1','shot_id':shot.id,'rsa_id':rsa.id,'rsa_hash':rsa.result_hash,'primary_artifact_id':primary.id,
        'mode':mode,'only_window_index':only_window_index,
        'images':[{'id':r.id,'seal':r.seal,'url':r.data['image']['url'],'sha256':r.data['image']['sha256']} for r in images]}
    return {**body,'seal':digest(body)}


def validate_video_binding(db,task,binding,*,validation_metrics=None,validation_proof=None):
    from app.services.rsa_media_contract import ValidationMemo
    memo=ValidationMemo()
    try:
        if not isinstance(binding,dict) or binding.get('seal')!=digest({k:v for k,v in binding.items() if k!='seal'}) or binding.get('shot_id')!=task.shot_id:
            raise HTTPException(409,'VIDEO_RSA_BINDING_REQUIRED')
        rsa,primary=require_primary(db,task.shot_id,memo=memo)
        if (rsa.id!=binding['rsa_id'] or rsa.result_hash!=binding['rsa_hash'] or primary.id!=binding['primary_artifact_id']):raise HTTPException(409,'VIDEO_RSA_OR_PRIMARY_CHANGED')
        from app.services.task_execution import execution_record
        execution=execution_record(task)
        if not execution:raise HTTPException(409,'VIDEO_EXECUTION_REQUIRED')
        request=execution['request']
        expected=video_binding(db,SimpleNamespace(**execution['shot_snapshot']),request['selected_mode'],request['only_window_index'],memo=memo)
        if binding!=expected:raise HTTPException(409,'VIDEO_REFERENCE_MANIFEST_CHANGED')
        for image in binding['images']:
            row=artifact_proof(db,image['id'],rsa_id=rsa.id,rsa_hash=rsa.result_hash,memo=memo)
            if row.seal!=image['seal'] or row.data['image']['url']!=image['url'] or row.data['image']['sha256']!=image['sha256']:
                raise HTTPException(409,'VIDEO_IMAGE_LINEAGE_CHANGED')
        if validation_proof is not None:
            validation_proof.clear();validation_proof.update(build_validated_binding_proof(db,task,binding,memo))
        return rsa
    finally:
        if validation_metrics is not None:
            validation_metrics.clear();validation_metrics.update(memo.report())


def resolved_text_context(rsa):
    logic=rsa.inputs['logical']
    return {'characters':[c['definition']['name'] for c in logic['characters']],
        'character_appearances':{c['definition']['name']:(c['appearance_definition']['description'] if c['appearance_id'] else c['definition']['appearance']) for c in logic['characters']},
        'prop_appearances':{p['definition']['name']:p['definition']['appearance'] for p in logic['props']},
        'scene_setting':logic['scene']['definition']['setting'],
        'resolved_shot_assets':{'id':rsa.id,'hash':rsa.result_hash}}


def video_batch_member(db, parent, shot_id, memo=None):
    from app.models.task import Task
    parent = db.query(Task).filter_by(id=parent.id).populate_existing().first()
    if not parent or parent.status not in {'pending', 'running'}:
        raise HTTPException(409, 'VIDEO_BATCH_NOT_ACTIVE')
    data = json.loads(parent.metadata_json or '{}')
    validate_source_pin(db, shot_id, data.get('source_pins', {}).get(shot_id))
    rsa, primary = require_primary(db, shot_id, memo=memo)
    expected = {'rsa_id': rsa.id, 'rsa_hash': rsa.result_hash, 'primary_id': primary.id}
    if data.get('asset_pins', {}).get(shot_id) != expected:
        raise HTTPException(409, 'VIDEO_BATCH_ASSET_PIN_CHANGED')


def runtime_checks(db, shot_id):
    """Read-only UI facts, evaluated by the same service gates as runtime admission."""
    shot = db.get(Shot, shot_id)
    if not shot: raise HTTPException(404, '分镜不存在')
    checks = {}
    def check(name, operation):
        try:
            operation()
            checks[name] = {'ready': True, 'reason': None}
        except (HTTPException, ValueError, KeyError, TypeError, OSError) as exc:
            checks[name] = {'ready': False, 'reason': exc.detail if isinstance(exc, HTTPException) else str(exc)}
    check('source', lambda: require_source(db, shot_id))
    check('assets', lambda: require_rsa(db, shot_id))
    check('primary', lambda: require_primary(db, shot_id))
    def audio():
        from app.services.audio_drive_service import AudioDriveService
        service = AudioDriveService(db)
        timeline = service.repo.latest_timeline(shot_id)
        if not timeline or timeline.status != 'READY' or shot.audio_status != 'READY':
            raise HTTPException(409, 'AUDIO_TIMELINE_NOT_READY')
        service._timeline_gate(shot_id, timeline, audio_source_pin(db, shot_id))
    def planning():
        require_source(db, shot_id)
        plan = json.loads(shot.video_director_plan or '{}')
        if plan.get('selected_mode') not in {'SINGLE_FRAME','FIRST_LAST_FRAME','MULTI_KEYFRAME'} or plan.get('keyframe_planning_status') in {'FAILED','STALE'}:
            raise HTTPException(409, 'VIDEO_PLAN_NOT_READY')
    def frames():
        planning()
        video_binding(db, shot)
    check('audio', audio)
    check('plan', planning)
    check('keyframes', frames)
    return {'shotId': shot_id, 'checks': checks}
