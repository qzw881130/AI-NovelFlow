"""Merge only complete, source-pinned production video receipts; preserve historical files."""
import json
import os
import threading
from copy import deepcopy
from datetime import datetime,timedelta
from pathlib import Path
from time import monotonic
from uuid import UUID,uuid4,uuid5
from fastapi import HTTPException
from sqlalchemy import case
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.services.chapter_asset_parse_service import digest, source_hash
from app.services.runtime_gate import source_pin
from app.services.task_execution import metadata, execution_purpose
from app.services.shot_video_execution import completed_video_artifact, file_digest, digest as video_digest


COMPLETION_VERSION='chapter-completion-manifest-v2'
LEGACY_ENTRY_PROOF_VERSION='verified-completion-entry-v1'
ENTRY_PROOF_VERSION='verified-completion-entry-v2'
REQUEST_VERSION='chapter-completion-request-v1'
REQUEST_NAMESPACE=UUID('a3f50318-a248-4c9b-a0cf-14373610d7cc')
HEARTBEAT_INTERVAL_SECONDS=15
LEGACY_DEPENDENCY_FENCE_VERSION='completion-binding-dependency-v1'
DEPENDENCY_FENCE_VERSION='completion-binding-dependency-v2'


def _dt(value):
    return value.isoformat() if value else None


def _json_safe(value):
    return json.loads(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str))


def _file_stat(path):
    value=Path(path);stat=value.stat()
    return {'path':str(value.resolve()),'device':stat.st_dev,'inode':stat.st_ino,'size':stat.st_size,
        'mtime_ns':stat.st_mtime_ns,'ctime_ns':stat.st_ctime_ns}


def _require_completion_dialect(db):
    if db.get_bind().dialect.name!='sqlite':raise HTTPException(409,'CHAPTER_COMPLETION_DIALECT_UNSUPPORTED')


def _begin_completion_snapshot(db):
    connection=db.connection()
    raw=getattr(connection.connection,'dbapi_connection',connection.connection)
    if not getattr(raw,'in_transaction',False):
        connection.exec_driver_sql('BEGIN')
        db.expire_all()


def _subtitle_receipt(path,expected_media_sha256):
    from app.services.rendered_subtitles import load_against_receipt,sidecar,snapshot_digest
    snapshot=load_against_receipt(path,expected_media_sha256)
    if not snapshot or snapshot.get('unavailable'):
        raise HTTPException(409,'VIDEO_SUBTITLE_LINEAGE_REQUIRED')
    envelope=json.loads(sidecar(path).read_text(encoding='utf-8'))
    return {'snapshot_hash':snapshot_digest(snapshot),'envelope_hash':envelope['sha256'],
        'media_sha256':snapshot['media_sha256'],'sidecar_stat':_file_stat(sidecar(path))},snapshot


def _durable_binding_validation_proof(proof):
    proof=proof if isinstance(proof,dict) else {}
    value={key:deepcopy(proof.get(key)) for key in (
        'version','bindingFingerprint','dependencyFingerprint','files')}
    if (not all(value.get(key) for key in ('version','bindingFingerprint','dependencyFingerprint'))
            or not isinstance(value.get('files'),dict) or not value['files']):
        raise HTTPException(409,'CHAPTER_COMPLETION_BINDING_PROOF_REQUIRED')
    return value


def _task_fence(task,data):
    return {'id':task.id,'type':task.type,'status':task.status,'novel_id':task.novel_id,
        'chapter_id':task.chapter_id,'shot_id':task.shot_id,'parent_task_id':task.parent_task_id,
        'workflow_id':task.workflow_id,'attempt':task.attempt,'result_url':task.result_url,
        'completed_at':_dt(task.completed_at),'metadata_hash':digest(data)}


def _revision_fence(db,shot):
    from app.models.shot_revision import ShotRevision,ShotRevisionHead
    head=db.get(ShotRevisionHead,shot.id);revision=db.get(ShotRevision,head.revision_id) if head and head.revision_id else None
    return {'base_run_id':head.base_run_id if head else None,'revision_id':head.revision_id if head else None,
        'revision':head.revision if head else 0,'revision_seal':revision.seal if revision else None}


def _row_hash(row):
    return digest(_json_safe({column.key:getattr(row,column.key) for column in row.__table__.columns})) if row else None


def _current_source_pin(db,shot):
    from app.models.chapter_shot_split import ShotSource
    from app.models.shot_revision import ShotRevision,ShotRevisionHead
    source=db.get(ShotSource,shot.id);head=db.get(ShotRevisionHead,shot.id)
    revision=db.get(ShotRevision,head.revision_id) if head and head.revision_id else None
    payload=revision.payload if revision and isinstance(revision.payload,dict) else {}
    render=(revision.seal if payload.get('dependency_version','legacy-v1')=='legacy-v1'
        else payload.get('render_seal')) if revision else source.seal if source else None
    return {'version':'runtime-source-v1','shot_id':shot.id,'split_run_id':source.run_id if source else None,
        'source_hash':source.source_hash if source else None,'seal':render}


def _source_dependency_fence(db,shot,memo=None):
    from app.models.chapter_governance import ChapterLifecycle,ChapterRebuildRun
    from app.models.chapter_shot_split import ChapterShotSplitRun,ShotSource
    from app.models.llm_log import LLMLog
    from app.models.shot_revision import ShotRevision,ShotRevisionHead
    from app.services.chapter_scope import collect_scope
    from app.services.chapter_shot_split_service import (audio_snapshot,checked_run,snapshot,
        source_contract_version_for_run,source_payload)
    memo={} if memo is None else memo;source=db.get(ShotSource,shot.id)
    run=db.get(ChapterShotSplitRun,source.run_id) if source else None
    run_key=('source_run',run.id if run else None)
    if run_key not in memo:
        task=db.get(Task,run.task_id) if run else None
        call=run.call if run and isinstance(run.call,dict) else {};log=db.get(LLMLog,call.get('llm_log_id')) if call.get('llm_log_id') else None
        basis=(collect_scope(db,run.novel_id,run.chapter_id,source_contract_version_for_run(run),run_profile=run.version)
            if run else None)
        if run:checked_run(db,run,basis)
        memo[run_key]={'run_hash':_row_hash(run),'task_hash':_row_hash(task),'log_hash':_row_hash(log),
            'current_basis_hash':digest(_json_safe(basis)) if basis else None}
    latest=(db.query(ChapterShotSplitRun.id).filter_by(chapter_id=shot.chapter_id)
        .order_by(ChapterShotSplitRun.created_at.desc(),ChapterShotSplitRun.id.desc()).first())
    lifecycle=db.get(ChapterLifecycle,shot.chapter_id);rebuild=db.get(ChapterRebuildRun,lifecycle.rebuild_id) if lifecycle and lifecycle.rebuild_id else None
    rebuild_task=db.get(Task,rebuild.task_id) if rebuild else None
    head=db.get(ShotRevisionHead,shot.id);chain=[];revision_id=head.revision_id if head else None;seen=set()
    while revision_id and revision_id not in seen:
        seen.add(revision_id);revision=db.get(ShotRevision,revision_id)
        if not revision:chain.append({'missing':revision_id});break
        task=db.get(Task,revision.task_id) if revision.task_id else None
        chain.append({'revision_hash':_row_hash(revision),'task_hash':_row_hash(task)})
        revision_id=revision.parent_id
    value={'version':'completion-source-dependency-v1','source_hash':digest(_json_safe(source_payload(source))) if source else None,
        'source_seal':source.seal if source else None,'current_shot_hash':digest(_json_safe(snapshot(shot))),
        'current_audio_hash':digest(_json_safe(audio_snapshot(db,shot.id))),
        'run':memo[run_key],'latest_run_id':latest[0] if latest else None,
        'lifecycle_hash':_row_hash(lifecycle),'rebuild_hash':_row_hash(rebuild),
        'rebuild_task_hash':_row_hash(rebuild_task),
        'revision_head_hash':_row_hash(head),'revision_chain':chain}
    return {'version':value['version'],'snapshot_hash':digest(value)}


def _compact_artifact_fence(db,artifact_id,seen=None,memo=None):
    from app.models.llm_log import LLMLog
    from app.models.rsa_media import RsaImageAttempt,RsaMediaArtifact
    from app.models.resolved_shot_assets import ResolvedImageVersion
    from app.services import appearance_image_contract as image_files
    memo={} if memo is None else memo
    if not artifact_id:return {'artifact':None,'attempt':None,'llm_log_hash':None,'parents':[]}
    if artifact_id in memo.get('artifacts',{}):return memo['artifacts'][artifact_id]
    seen=set() if seen is None else set(seen)
    if artifact_id in seen:return {'cycle':artifact_id}
    seen.add(artifact_id);row=db.get(RsaMediaArtifact,artifact_id);attempt=db.get(RsaImageAttempt,row.task_id) if row else None
    data=row.data if row and isinstance(row.data,dict) else {}
    execution=attempt.execution if attempt and isinstance(attempt.execution,dict) else {}
    prompt=execution.get('prompt') if isinstance(execution.get('prompt'),dict) else {}
    log=db.get(LLMLog,prompt.get('llm_log_id')) if prompt.get('llm_log_id') else None;parents=[]
    for parent in data.get('parents') if isinstance(data.get('parents'),list) else []:
        if isinstance(parent,dict) and parent.get('kind')=='ARTIFACT':
            parents.append(_compact_artifact_fence(db,parent.get('id'),seen,memo))
        elif isinstance(parent,dict):
            reference=parent.get('reference') if isinstance(parent.get('reference'),dict) else {}
            revision=db.get(ResolvedImageVersion,reference.get('image_revision_id')) if reference.get('image_revision_id') else None
            revision_data=revision.data if revision and isinstance(revision.data,dict) else {}
            parents.append({'reference_hash':digest(reference),'revision':({'id':revision.id,'seal':revision.seal,
                'origin_hash':revision.origin_hash,'data_hash':digest(revision_data),'row_hash':_row_hash(revision)} if revision else None),
                'source':image_files.image_source_signature((revision_data.get('snapshot') or {}).get('url'))})
        else:parents.append(parent)
    result={'artifact':({'id':row.id,'task_id':row.task_id,'shot_id':row.shot_id,'rsa_id':row.rsa_id,
            'stage':row.stage,'frame_index':row.frame_index,'seal':row.seal,'data_hash':digest(data),
            'source':image_files.image_source_signature((data.get('image') or {}).get('url')),
            'row_hash':_row_hash(row)} if row else None),
        'attempt':({'id':attempt.id,'status':attempt.status,'artifact_id':attempt.artifact_id,
            'input_hash':attempt.input_hash,'rsa_id':attempt.rsa_id,'rsa_hash':attempt.rsa_hash,
            'inputs_hash':digest(attempt.inputs),'execution_hash':digest(attempt.execution),
            'row_hash':_row_hash(attempt)} if attempt else None),
        'llm_log_hash':(digest({key:getattr(log,key) for key in ('id','status','response','system_prompt',
            'user_prompt','novel_id','chapter_id','task_type','provider','model','request_info')}) if log else None),
        'parents':parents}
    memo.setdefault('artifacts',{})[artifact_id]=result
    return result


def _legacy_normal_dependency_fence(db,shot,binding,file_dependencies=None):
    from app.services.runtime_gate import binding_dependency_snapshot
    urls=(list(file_dependencies) if isinstance(file_dependencies,list) else
        [item.get('url') for item in binding.get('images',[]) if isinstance(item,dict) and item.get('url')])
    snapshot=binding_dependency_snapshot(db,db.get(Task,shot.video_task_id),binding,urls)
    snapshot.pop('processId',None);snapshot.pop('database',None)
    snapshot['version']=LEGACY_DEPENDENCY_FENCE_VERSION;snapshot=_json_safe(snapshot)
    return {'version':LEGACY_DEPENDENCY_FENCE_VERSION,'snapshot_hash':digest(snapshot),
        'file_dependencies':sorted(urls)}


def _normal_dependency_fence(db,shot,binding,file_dependencies=None,validation_proof=None,memo=None):
    from app.models.resolved_shot_assets import ResolvedShotAssets,ShotAssetHead
    from app.services import appearance_image_contract as image_files
    from app.services.runtime_gate import _live_asset_state
    memo={} if memo is None else memo;validation_proof=validation_proof if isinstance(validation_proof,dict) else {}
    expected_files=validation_proof.get('files') if isinstance(validation_proof.get('files'),dict) else {}
    if (validation_proof.get('bindingFingerprint')!=digest(binding)
            or not validation_proof.get('dependencyFingerprint') or not expected_files):
        raise HTTPException(409,'CHAPTER_COMPLETION_BINDING_PROOF_REQUIRED')
    urls=(sorted(expected_files) if expected_files else list(file_dependencies) if isinstance(file_dependencies,list) else
        [item.get('url') for item in binding.get('images',[]) if isinstance(item,dict) and item.get('url')])
    head=db.get(ShotAssetHead,shot.id);rsa=db.get(ResolvedShotAssets,binding.get('rsa_id')) if isinstance(binding,dict) else None
    rsa_task=db.get(Task,rsa.task_id) if rsa and rsa.task_id else None
    current_files={url:image_files.image_source_signature(url) for url in sorted(urls)}
    if current_files!=expected_files:raise HTTPException(409,'CHAPTER_COMPLETION_BINDING_FILES_CHANGED')
    snapshot={'version':DEPENDENCY_FENCE_VERSION,'binding_hash':digest(binding),
        'validated_dependency_fingerprint':validation_proof['dependencyFingerprint'],
        'rsa_head':{'rsa_id':head.rsa_id if head else None,'revision':head.revision if head else None,
            'row_hash':_row_hash(head)},
        'rsa':({'id':rsa.id,'revision':rsa.revision,'status':rsa.status,'input_hash':rsa.input_hash,
            'result_hash':rsa.result_hash,'seal':rsa.seal,'task_id':rsa.task_id,'row_hash':_row_hash(rsa)} if rsa else None),
        'rsa_task':(_task_fence(rsa_task,metadata(rsa_task)) if rsa_task else None),
        'live_assets_hash':digest(_json_safe(_live_asset_state(db,rsa))),
        'artifacts':[_compact_artifact_fence(db,item.get('id'),memo=memo) for item in binding.get('images',[])],
        'files':current_files}
    return {'version':DEPENDENCY_FENCE_VERSION,'snapshot_hash':digest(_json_safe(snapshot)),
        'file_dependencies':sorted(urls)}


def _entry_fence(db,shot,task,kind,media,*,captured=False,dependency_version=None,
        proof_version=ENTRY_PROOF_VERSION,memo=None):
    data=metadata(task);path=Path(media['path'])
    subtitle=(deepcopy(media.get('subtitle_receipt')) if captured and isinstance(media.get('subtitle_receipt'),dict)
        else _subtitle_receipt(path,media['sha256'])[0])
    legacy=proof_version==LEGACY_ENTRY_PROOF_VERSION
    if proof_version not in {LEGACY_ENTRY_PROOF_VERSION,ENTRY_PROOF_VERSION}:
        raise HTTPException(409,'CHAPTER_COMPLETION_PROOF_STALE')
    current_source_pin=source_pin(db,shot.id) if legacy else (
        deepcopy(media.get('source_pin')) if captured else _current_source_pin(db,shot))
    value={'source_pin':current_source_pin,'revision':_revision_fence(db,shot),
        'shot':{'id':shot.id,'index':shot.index,'completion_disposition':shot.completion_disposition,
            'image_url':shot.image_url,'image_path':shot.image_path,'image_status':shot.image_status,
            'image_task_id':shot.image_task_id,
            'video_task_id':shot.video_task_id,'video_status':shot.video_status,'video_url':shot.video_url,
            'video_director_plan_revision':shot.video_director_plan_revision,
            'video_director_plan_hash':digest(shot.video_director_plan or '{}')},
        'producer':_task_fence(task,data),'media_stat':_file_stat(path),'subtitle':subtitle}
    if not legacy:value['source_dependency']=_source_dependency_fence(db,shot,memo)
    if kind=='NORMAL_VIDEO':
        dependency=_legacy_normal_dependency_fence if dependency_version==LEGACY_DEPENDENCY_FENCE_VERSION else _normal_dependency_fence
        if dependency_version not in {None,LEGACY_DEPENDENCY_FENCE_VERSION,DEPENDENCY_FENCE_VERSION}:
            raise HTTPException(409,'CHAPTER_COMPLETION_PROOF_STALE')
        value['dependency']=dependency(db,shot,data.get('rsa_binding'),media.get('binding_file_dependencies')) if dependency==_legacy_normal_dependency_fence else dependency(
            db,shot,data.get('rsa_binding'),media.get('binding_file_dependencies'),media.get('binding_validation_proof'),memo)
    else:
        from app.services.narration_card_service import capture
        current_input_hash=digest(capture(db,shot.id))
        if current_input_hash!=data.get('input_hash'):raise HTTPException(409,'CHAPTER_COMPLETION_PROOF_STALE')
        value['dependency']={'input_hash':data.get('input_hash'),'current_input_hash':current_input_hash,
            'result_hash':digest(data.get('result') or {})}
    return value


def _proof(db,shot,task,kind,media,memo=None):
    value={'version':ENTRY_PROOF_VERSION,'kind':kind,'fence':_entry_fence(
        db,shot,task,kind,media,captured=True,proof_version=ENTRY_PROOF_VERSION,memo=memo)}
    return {**value,'proof_hash':digest(value)}


def _verify_entry_proof(proof,kind,current_fence):
    if proof.get('version') not in {LEGACY_ENTRY_PROOF_VERSION,ENTRY_PROOF_VERSION} or proof.get('kind')!=kind:
        raise HTTPException(409,'CHAPTER_COMPLETION_ENTRY_CHANGED')
    unsigned={key:value for key,value in proof.items() if key!='proof_hash'}
    if proof.get('proof_hash')!=digest(unsigned):raise HTTPException(409,'CHAPTER_COMPLETION_PROOF_TAMPERED')
    if proof.get('fence')!=current_fence:raise HTTPException(409,'CHAPTER_COMPLETION_PROOF_STALE')
    return True


def _entry_subtitle_snapshot_hash(entry, snapshot):
    return video_digest(snapshot) if entry['kind']=='NORMAL_VIDEO' else digest(snapshot)


def video_receipt(db, shot, *, require_subtitle=False, validation_metrics=None):
    started=monotonic()
    pin = source_pin(db, shot.id)
    task = db.get(Task, shot.video_task_id) if shot.video_task_id else None
    if not task or task.type != 'shot_video' or task.status != 'completed' or execution_purpose(task) != 'production':
        raise HTTPException(409, 'VERIFIED_SHOT_VIDEO_REQUIRED')
    data = metadata(task)
    receipt_metrics={}
    verified = completed_video_artifact(db, task.id, shot_id=shot.id,validation_metrics=receipt_metrics)
    if not verified['success']:
        raise HTTPException(409, verified['message'])
    run = data.get('video_run') or {}
    result = verified.get('result') or {}
    if (run.get('phase') != 'completed' or run.get('scope') != 'whole_shot' or result.get('attachment') != 'attached'
            or task.shot_id != shot.id or shot.video_status != 'completed' or result.get('url') != shot.video_url
            or task.result_url != shot.video_url):
        raise HTTPException(409, 'VIDEO_COMPLETION_LINEAGE_REQUIRED')
    # A changed director plan cannot silently reuse an old completed video.
    expected_plan = json.loads(data['execution']['working_shot']['video_director_plan'] or '{}')
    expected_plan.update(merged_video_url=result['url'], merged_at=task.completed_at.isoformat(),
                         video_execution_task_id=task.id, video_execution_attempt_id=run['run_id'])
    for key in ('error_message', 'task_error_message'):
        expected_plan.pop(key, None)
    if json.loads(shot.video_director_plan or '{}') != expected_plan:
        raise HTTPException(409, 'VIDEO_PLAN_CHANGED_AFTER_PUBLICATION')
    path = Path(result['path'])
    if not path.is_file() or path.stat().st_size != result['bytes']:
        raise HTTPException(409, 'VIDEO_RESULT_BYTES_CHANGED')
    _subtitle,subtitle_snapshot=_subtitle_receipt(path,result['sha256'])
    if require_subtitle and (not subtitle_snapshot or subtitle_snapshot.get('unavailable')
            or result.get('subtitle_snapshot_hash')!=video_digest(subtitle_snapshot)):
        raise HTTPException(409,'VIDEO_SUBTITLE_LINEAGE_REQUIRED')
    if validation_metrics is not None:
        validation_metrics.clear();validation_metrics.update({**receipt_metrics,
            'full_video_receipt_count':1,'elapsed_ms':round((monotonic()-started)*1000,3)})
    binding_proof=_durable_binding_validation_proof(verified.get('binding_validation_proof'))
    return {'shot_id': shot.id, 'source_pin': pin, 'task_id': task.id, 'run_id': run['run_id'],
            'rsa_binding': data['rsa_binding'], 'path': str(path), 'sha256': result['sha256'],
            'bytes':result['bytes'],'stat':_file_stat(path),'subtitle_snapshot_hash':_subtitle['snapshot_hash'],
            'subtitle_receipt':_subtitle,
            'binding_file_dependencies':sorted(binding_proof['files']),
            'binding_validation_proof':binding_proof,
            'producer_subtitle_snapshot_hash':result.get('subtitle_snapshot_hash'),
            'result': deepcopy(result)}


def capture_merge(db, novel_id, chapter_id, shot_ids=None, mode='shots_only'):
    if mode != 'shots_only':
        raise HTTPException(410, 'INDEX_BASED_TRANSITION_MERGE_RETIRED')
    chapter = db.query(Chapter).filter_by(id=chapter_id, novel_id=novel_id).first()
    if not chapter:
        raise HTTPException(404, '章回不存在')
    shots = db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index, Shot.id).all()
    all_ids = [shot.id for shot in shots]
    selected = set(shot_ids) if shot_ids is not None else set(all_ids)
    if not selected or selected - set(all_ids):
        raise HTTPException(409, 'MERGE_MEMBERSHIP_INVALID')
    return {'version': 'chapter-video-rsa-v1', 'novel_id': novel_id, 'chapter_id': chapter_id, 'mode': mode,
            'chapter_members': all_ids, 'previous_final_video': chapter.final_video,
            'videos': [video_receipt(db, shot) for shot in shots if shot.id in selected]}


def capture_completion(db,novel_id,chapter_id,metrics=None):
    _require_completion_dialect(db)
    _begin_completion_snapshot(db)
    captured_at=monotonic();per_shot=[];proof_memo={}
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).populate_existing().first()
    if not chapter:raise HTTPException(404,'章回不存在')
    shots=db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index,Shot.id).all()
    if not shots or [shot.index for shot in shots]!=list(range(1,len(shots)+1)):
        raise HTTPException(409,'CHAPTER_COMPLETION_SHOT_ORDER_INVALID')
    entries=[];cursor=0;split_run_id=None;current_source_hash=source_hash(chapter)
    for ordinal,shot in enumerate(shots,1):
        shot_started=monotonic();receipt_metrics={}
        source=shot.source_record
        if not source or source.source_hash!=current_source_hash or source.source_start<cursor:
            raise HTTPException(409,'CHAPTER_COMPLETION_SOURCE_INVALID')
        if chapter.content[cursor:source.source_start].strip():raise HTTPException(409,'CHAPTER_COMPLETION_SOURCE_GAP')
        cursor=source.source_end
        if split_run_id is None:split_run_id=source.run_id
        if source.run_id!=split_run_id:raise HTTPException(409,'CHAPTER_COMPLETION_MIXED_SPLIT_RUNS')
        disposition=getattr(shot,'completion_disposition','NORMAL') or 'NORMAL'
        ownership={'start':source.source_start,'end':source.source_end,'source_hash':source.source_hash,
            'source_seal':source.seal,'text_hash':digest(chapter.content[source.source_start:source.source_end])}
        if disposition=='NORMAL':
            media=video_receipt(db,shot,require_subtitle=True,validation_metrics=receipt_metrics);kind='NORMAL_VIDEO'
        elif disposition=='DEGRADED_NARRATION_CARD':
            from app.services.narration_card_service import completed_artifact
            media=completed_artifact(db,shot);kind='DEGRADED_NARRATION_CARD'
        else:raise HTTPException(409,'CHAPTER_COMPLETION_DISPOSITION_UNSUPPORTED')
        task=db.get(Task,media['task_id']);media={**media,'stat':media.get('stat') or _file_stat(media['path'])}
        if not isinstance(media.get('subtitle_receipt'),dict):media['subtitle_receipt']=_subtitle_receipt(media['path'],media['sha256'])[0]
        proof=_proof(db,shot,task,kind,media,proof_memo)
        entries.append({'ordinal':ordinal,'kind':kind,'shot_id':shot.id,'shot_index':shot.index,
            'ownership':ownership,'media':media,'proof':proof})
        per_shot.append({'shot_id':shot.id,'shot_index':shot.index,'kind':kind,
            'elapsed_ms':round((monotonic()-shot_started)*1000,3),**receipt_metrics})
    if chapter.content[cursor:].strip():raise HTTPException(409,'CHAPTER_COMPLETION_SOURCE_GAP')
    normal=sum(row['kind']=='NORMAL_VIDEO' for row in entries);degraded=len(entries)-normal
    manifest={'version':COMPLETION_VERSION,'novel_id':novel_id,'chapter_id':chapter_id,
        'source':{'split_run_id':split_run_id,'source_hash':current_source_hash,
            'length_codepoints':len(chapter.content),'offset_unit':'UNICODE_CODE_POINT'},
        'entries':entries,'counts':{'normal':normal,'degraded':degraded,'total':len(entries)}}
    if metrics is not None:
        metrics.clear();metrics.update({'version':'completion-capture-metrics-v1','full_video_receipt_count':normal,
            'full_degraded_receipt_count':degraded,'validate_video_binding_count':sum(
                row.get('validate_video_binding_count',0) for row in per_shot),
            'video_sha256_count':sum(row.get('video_sha256_count',0) for row in per_shot),
            'video_sha256_bytes':sum(row.get('video_sha256_bytes',0) for row in per_shot),
            'lineage_proof_reconstruction_count':sum(row.get('lineage_proof_reconstruction_count',0) for row in per_shot),
            'per_shot':per_shot,'total_ms':round((monotonic()-captured_at)*1000,3)})
    return manifest


def verify_completion_manifest(db,novel_id,chapter_id,manifest,metrics=None):
    _require_completion_dialect(db)
    _begin_completion_snapshot(db)
    started=monotonic();proof_memo={}
    if (not isinstance(manifest,dict) or manifest.get('version')!=COMPLETION_VERSION
            or manifest.get('novel_id')!=novel_id or manifest.get('chapter_id')!=chapter_id):
        raise HTTPException(409,'CHAPTER_COMPLETION_PROOF_REQUIRED')
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).populate_existing().first()
    shots=db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index,Shot.id).all() if chapter else []
    entries=manifest.get('entries') if isinstance(manifest.get('entries'),list) else []
    if (not chapter or len(shots)!=len(entries) or source_hash(chapter)!=manifest.get('source',{}).get('source_hash')
            or [shot.id for shot in shots]!=[entry.get('shot_id') for entry in entries]):
        raise HTTPException(409,'CHAPTER_COMPLETION_MEMBERSHIP_CHANGED')
    cursor=0
    for ordinal,(shot,entry) in enumerate(zip(shots,entries),1):
        source=shot.source_record;ownership=entry.get('ownership') or {};proof=entry.get('proof') or {}
        if (entry.get('ordinal')!=ordinal or entry.get('shot_index')!=shot.index or not source
                or chapter.content[cursor:source.source_start].strip()
                or ownership!={'start':source.source_start,'end':source.source_end,'source_hash':source.source_hash,
                    'source_seal':source.seal,'text_hash':digest(chapter.content[source.source_start:source.source_end])}):
            raise HTTPException(409,'CHAPTER_COMPLETION_SOURCE_CHANGED')
        cursor=source.source_end
        kind='NORMAL_VIDEO' if (shot.completion_disposition or 'NORMAL')=='NORMAL' else 'DEGRADED_NARRATION_CARD'
        if entry.get('kind')!=kind:raise HTTPException(409,'CHAPTER_COMPLETION_ENTRY_CHANGED')
        media=entry.get('media') or {};task=db.get(Task,media.get('task_id'))
        if not task:raise HTTPException(409,'CHAPTER_COMPLETION_PROOF_STALE')
        dependency_version=((proof.get('fence') or {}).get('dependency') or {}).get('version') if kind=='NORMAL_VIDEO' else None
        _verify_entry_proof(proof,kind,_entry_fence(db,shot,task,kind,media,dependency_version=dependency_version,
            proof_version=proof.get('version'),memo=proof_memo))
    if chapter.content[cursor:].strip():raise HTTPException(409,'CHAPTER_COMPLETION_SOURCE_CHANGED')
    if metrics is not None:
        metrics.clear();metrics.update({'version':'completion-guard-metrics-v1','checks':1,
            'proof_reuses':len(entries),'full_video_receipt_count':0,'validate_video_binding_count':0,
            'video_sha256_count':0,'lineage_proof_reconstruction_count':0,
            'source_governance_validation_count':1 if entries else 0,
            'degraded_freshness_capture_count':sum(entry.get('kind')=='DEGRADED_NARRATION_CARD' for entry in entries),
            'elapsed_ms':round((monotonic()-started)*1000,3)})
    return True


def completion_request_snapshot(db,novel_id,chapter_id,retry_failed_task_id=None):
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).first()
    if not chapter:raise HTTPException(404,'章回不存在')
    shots=db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index,Shot.id).all()
    if not shots:raise HTTPException(409,'CHAPTER_COMPLETION_SHOTS_REQUIRED')
    retry=None
    if retry_failed_task_id:
        retry=db.get(Task,retry_failed_task_id)
        value=metadata(retry) if retry else {}
        if (not retry or retry.type!='chapter_video' or retry.chapter_id!=chapter_id or retry.novel_id!=novel_id
                or retry.status!='failed' or value.get('delivery_mode')!='CHAPTER_COMPLETION'):
            raise HTTPException(409,'CHAPTER_COMPLETION_RETRY_PARENT_INVALID')
    snapshot={'version':REQUEST_VERSION,'novel_id':novel_id,'chapter_id':chapter_id,
        'source_hash':source_hash(chapter),'retry_failed_task_id':retry_failed_task_id,
        'shots':[{'id':shot.id,'index':shot.index,'completion_disposition':shot.completion_disposition,
            'video_task_id':shot.video_task_id,'video_status':shot.video_status,
            'video_director_plan_revision':shot.video_director_plan_revision} for shot in shots]}
    return snapshot


def admit_completion(db,novel_id,chapter_id,*,expected_manifest_hash=None,retry_failed_task_id=None):
    _require_completion_dialect(db)
    if db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).update({'id':chapter_id},synchronize_session=False)!=1:
        raise HTTPException(404,'章回不存在')
    db.expire_all();chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).populate_existing().one()
    snapshot=completion_request_snapshot(db,novel_id,chapter_id,retry_failed_task_id)
    request={'snapshot':snapshot,'expected_manifest_hash':expected_manifest_hash};request_hash=digest(request)
    task_id=str(uuid5(REQUEST_NAMESPACE,request_hash))
    existing=db.get(Task,task_id)
    if existing:
        value=metadata(existing)
        if value.get('request_hash')!=request_hash:raise HTTPException(409,'CHAPTER_COMPLETION_REQUEST_ID_COLLISION')
        db.commit()
        return existing,False
    active=db.query(Task).filter_by(type='chapter_video',chapter_id=chapter_id).filter(Task.status.in_(['pending','running'])).first()
    if active:
        value=metadata(active)
        if value.get('request_hash')==request_hash:
            db.commit();return active,False
        raise HTTPException(409,'CHAPTER_COMPLETION_TASK_ACTIVE')
    value={'execution_purpose':'production','delivery_mode':'CHAPTER_COMPLETION',
        'request_snapshot':request,'request_hash':request_hash,'expected_manifest_hash':expected_manifest_hash,
        'retry_of':retry_failed_task_id,'capture_state':'PENDING',
        'previous_final_video':chapter.final_video,'previous_final_video_task_id':chapter.final_video_task_id}
    task=Task(id=task_id,type='chapter_video',status='pending',novel_id=novel_id,chapter_id=chapter_id,
        parent_task_id=retry_failed_task_id,name='完成章回视频',
        description='按 verified Chapter Completion Manifest 合并全部 NORMAL/NARRATION_CARD entries',
        progress=0,current_step='等待章回完整交付',metadata_json=json.dumps(value,ensure_ascii=False))
    db.add(task)
    try:db.commit()
    except Exception:
        db.rollback();task=db.get(Task,task_id)
        if not task or metadata(task).get('request_hash')!=request_hash:raise
        return task,False
    db.refresh(task);return task,True


class CompletionLease:
    def __init__(self,task_id,token,worker_id,attempt,encoded,interval=HEARTBEAT_INTERVAL_SECONDS):
        self.task_id,self.token,self.worker_id,self.attempt=task_id,token,worker_id,attempt
        self.encoded,self.interval=encoded,interval;self._lock=threading.Lock();self._stop=threading.Event()
        self._lost=threading.Event();self._thread=None;self._last=None;self._max_gap_ms=0;self._count=0

    def _update(self,values):
        from app.core.database import SessionLocal
        with self._lock:
            if self._lost.is_set():raise HTTPException(409,'CHAPTER_COMPLETION_OWNER_CHANGED')
            db=SessionLocal();now=datetime.utcnow()
            try:
                changed=db.query(Task).filter_by(id=self.task_id,status='running',claim_token=self.token,
                    worker_id=self.worker_id,attempt=self.attempt,metadata_json=self.encoded).update({
                        **values,'heartbeat_at':now},synchronize_session=False)
                if changed!=1:
                    db.rollback();self._lost.set();raise HTTPException(409,'CHAPTER_COMPLETION_OWNER_CHANGED')
                db.commit()
                tick=monotonic()
                if self._last is not None:self._max_gap_ms=max(self._max_gap_ms,(tick-self._last)*1000)
                self._last=tick;self._count+=1
            except Exception:
                db.rollback();self._lost.set();raise
            finally:db.close()

    def start(self):
        self._update({})
        def run():
            while not self._stop.wait(self.interval):
                try:self._update({})
                except Exception:return
        self._thread=threading.Thread(target=run,name=f'completion-heartbeat-{self.task_id}',daemon=True);self._thread.start()

    def checkpoint(self,progress=None,step=None):
        values={}
        if progress is not None:
            target=min(99,int(progress))
            values['progress']=case((Task.progress<target,target),else_=Task.progress)
        if step is not None:values['current_step']=step
        self._update(values)

    def replace_metadata(self,new_encoded):
        with self._lock:
            from app.core.database import SessionLocal
            db=SessionLocal();now=datetime.utcnow()
            try:
                changed=db.query(Task).filter_by(id=self.task_id,status='running',claim_token=self.token,
                    worker_id=self.worker_id,attempt=self.attempt,metadata_json=self.encoded).update({
                        'metadata_json':new_encoded,'heartbeat_at':now},synchronize_session=False)
                if changed!=1:
                    db.rollback();self._lost.set();raise HTTPException(409,'CHAPTER_COMPLETION_OWNER_CHANGED')
                db.commit();self.encoded=new_encoded
                tick=monotonic()
                if self._last is not None:self._max_gap_ms=max(self._max_gap_ms,(tick-self._last)*1000)
                self._last=tick;self._count+=1
            except Exception:
                db.rollback();self._lost.set();raise
            finally:db.close()

    def assert_owned(self):
        if self._lost.is_set():raise HTTPException(409,'CHAPTER_COMPLETION_OWNER_CHANGED')

    def stop(self):
        self._stop.set()
        if self._thread:self._thread.join(timeout=min(5,self.interval))

    def metrics(self):
        return {'version':'completion-heartbeat-metrics-v1','count':self._count,
            'max_gap_ms':round(self._max_gap_ms,3),'interval_seconds':self.interval,'lease_lost':self._lost.is_set()}


def completion_readiness(db,novel_id,chapter_id):
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).first()
    if not chapter:raise HTTPException(404,'章回不存在')
    shots=db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index,Shot.id).all();rows=[];capture_metrics={}
    latest=next((candidate for candidate in db.query(Task).filter_by(type='chapter_video',chapter_id=chapter_id)
        .order_by(Task.created_at.desc(),Task.id.desc()).all()
        if metadata(candidate).get('delivery_mode')=='CHAPTER_COMPLETION'),None)
    latest_task=({'taskId':latest.id,'status':latest.status,'error':latest.error_message} if latest else None)
    try:
        manifest=capture_completion(db,novel_id,chapter_id,metrics=capture_metrics)
        rows=[{'shotId':entry['shot_id'],'shotIndex':entry['shot_index'],
            'completionDisposition':'NORMAL' if entry['kind']=='NORMAL_VIDEO' else 'DEGRADED_NARRATION_CARD',
            'sourceRange':[entry['ownership']['start'],entry['ownership']['end']],
            'ready':True,'blocker':None} for entry in manifest['entries']]
        return {'ready':True,'manifestHash':digest(manifest),'counts':manifest['counts'],'entries':rows,
            'blocker':None,'captureMetrics':capture_metrics,'latestTask':latest_task}
    except HTTPException as captured:
        chapter_blocker=captured.detail
    for shot in shots:
        disposition=getattr(shot,'completion_disposition','NORMAL') or 'NORMAL';row_blocker=None
        try:
            if disposition=='NORMAL':video_receipt(db,shot)
            elif disposition=='DEGRADED_NARRATION_CARD':
                from app.services.narration_card_service import completed_artifact
                completed_artifact(db,shot)
            else:raise HTTPException(409,'CHAPTER_COMPLETION_DISPOSITION_UNSUPPORTED')
        except HTTPException as exc:row_blocker=exc.detail
        source=shot.source_record
        rows.append({'shotId':shot.id,'shotIndex':shot.index,'completionDisposition':disposition,
            'sourceRange':[source.source_start,source.source_end] if source else None,
            'ready':row_blocker is None,'blocker':row_blocker})
    return {'ready':False,'manifestHash':None,
        'counts':{'normal':sum(r['completionDisposition']=='NORMAL' for r in rows),
            'degraded':sum(r['completionDisposition']=='DEGRADED_NARRATION_CARD' for r in rows),'total':len(rows)},
        'entries':rows,'blocker':chapter_blocker,'latestTask':latest_task}


def current_completion(db,novel_id,chapter_id):
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).first()
    if not chapter:raise HTTPException(404,'章回不存在')
    task=db.get(Task,chapter.final_video_task_id) if chapter.final_video_task_id else None
    meta=metadata(task) if task else {};result=meta.get('result')
    manifest=meta.get('completion_manifest') if task else None
    if (not task or task.type!='chapter_video' or task.status!='completed' or task.result_url!=chapter.final_video
            or meta.get('execution_purpose')!='production' or meta.get('delivery_mode')!='CHAPTER_COMPLETION'
            or not isinstance(result,dict)
            or not isinstance(manifest,dict) or digest(manifest)!=meta.get('manifest_hash')
            or result.get('manifestHash')!=meta.get('manifest_hash')):return None
    try:
        verify_completion_manifest(db,novel_id,chapter_id,manifest)
    except (HTTPException,OSError,ValueError,KeyError,TypeError):return None
    from app.services.rendered_subtitles import load_against_receipt,snapshot_digest
    from app.utils.path_utils import local_path_to_url,url_to_local_path
    path=Path(result.get('path') or url_to_local_path(chapter.final_video) or '')
    snapshot=load_against_receipt(path,result.get('sha256')) if path.is_file() else None
    degraded=[{'shotId':row['shot_id'],'shotIndex':row['shot_index'],
        'sourceRange':[row['ownership']['start'],row['ownership']['end']]}
        for row in manifest['entries'] if row['kind']=='DEGRADED_NARRATION_CARD']
    expected_result={'outcome':'SUCCEEDED_WITH_DEGRADATION' if degraded else 'SUCCEEDED',
        'manifestHash':meta['manifest_hash'],'path':str(path),'url':chapter.final_video,
        'normalCount':manifest['counts']['normal'],'degradedCount':manifest['counts']['degraded'],
        'degradedRanges':degraded}
    if (not path.is_file() or _file_stat(path)!=result.get('stat')
            or not snapshot or snapshot.get('unavailable') or snapshot_digest(snapshot)!=result.get('subtitleSnapshotHash')):
        return None
    lineage=snapshot.get('lineage') or {};expected_media=[entry['media']['sha256'] for entry in manifest['entries']]
    if (lineage.get('kind')!='merge'
            or [row.get('source_sha256') for row in lineage.get('segments') or []]!=expected_media
            or len(lineage.get('sources') or [])!=len(manifest['entries'])
            or [_entry_subtitle_snapshot_hash(entry,row) for entry,row in zip(
                manifest['entries'],lineage.get('sources') or [])]!=[
                entry['media'].get('subtitle_snapshot_hash') for entry in manifest['entries']]):return None
    if (task.result_url!=chapter.final_video or local_path_to_url(str(path))!=chapter.final_video
            or any(result.get(key)!=value for key,value in expected_result.items())):return None
    return {'taskId':task.id,**deepcopy(result)}


async def run_completion(task_id):
    from app.core.database import SessionLocal
    from app.services.file_storage import file_storage
    from app.services.rendered_subtitles import snapshot_digest
    from app.utils.path_utils import local_path_to_url
    db=SessionLocal();token=str(uuid4());worker_id=f'chapter-completion:{os.getpid()}:{uuid4()}'
    lease=None;encoded=None;attempt=None
    try:
        task=db.get(Task,task_id)
        if not task or task.status!='pending':return
        encoded=task.metadata_json;meta=metadata(task);attempt=(task.attempt or 0)+1
        if (meta.get('execution_purpose')!='production' or meta.get('delivery_mode')!='CHAPTER_COMPLETION'
                or meta.get('request_hash')!=digest(meta.get('request_snapshot'))):
            raise HTTPException(409,'CHAPTER_COMPLETION_REQUEST_INVALID')
        if db.query(Task).filter_by(id=task.id,status='pending',metadata_json=encoded).update({
                'status':'running','claim_token':token,'worker_id':worker_id,'attempt':attempt,
                'claimed_at':datetime.utcnow(),'started_at':datetime.utcnow(),'heartbeat_at':datetime.utcnow(),
                'progress':1,'current_step':'校验 Chapter Completion Manifest'},synchronize_session=False)!=1:
            db.rollback();return
        db.commit()
        lease=CompletionLease(task_id,token,worker_id,attempt,encoded);lease.start()
        capture_metrics={};manifest=capture_completion(db,task.novel_id,task.chapter_id,metrics=capture_metrics)
        manifest_hash=digest(manifest)
        if meta.get('expected_manifest_hash') and meta['expected_manifest_hash']!=manifest_hash:
            raise HTTPException(409,'CHAPTER_COMPLETION_MANIFEST_CHANGED')
        meta={**meta,'capture_state':'VERIFIED','completion_manifest':manifest,'manifest_hash':manifest_hash,
            'capture_metrics':capture_metrics}
        new_encoded=json.dumps(meta,ensure_ascii=False);lease.replace_metadata(new_encoded);encoded=new_encoded
        db.rollback();db.expire_all()
        guard_metrics={};verify_completion_manifest(db,task.novel_id,task.chapter_id,manifest,guard_metrics)
        db.rollback();db.expire_all()
        lease.checkpoint(1,'Verified completion proof reused; preparing merge')
        directory=file_storage._get_story_dir(task.novel_id)/f'chapter_{task.chapter_id[:8]}'/'completion'/task.id
        directory.mkdir(parents=True,exist_ok=True);destination=directory/'chapter.mp4'
        async def progress(percent,step):
            lease.checkpoint(percent,step)
        result=await file_storage.merge_videos([entry['media']['path'] for entry in manifest['entries']],str(destination),
            progress_callback=progress,source_receipts=[entry['media'] for entry in manifest['entries']])
        if not result.get('success'):raise RuntimeError(result.get('message') or 'CHAPTER_COMPLETION_MERGE_FAILED')
        lease.assert_owned()
        expected=[entry['media']['sha256'] for entry in manifest['entries']]
        if [row.get('source_sha256') for row in result.get('media_segments') or []]!=expected:
            raise HTTPException(409,'CHAPTER_COMPLETION_MEDIA_ORDER_CHANGED')
        from app.services.rendered_subtitles import load_against_receipt
        final_snapshot=load_against_receipt(destination,result.get('output_sha256'))
        if (_file_stat(destination)!=result.get('output_stat') or destination.stat().st_size!=result.get('output_bytes')
                or not final_snapshot or final_snapshot.get('unavailable')):
            raise HTTPException(409,'CHAPTER_COMPLETION_SUBTITLE_LINEAGE_REQUIRED')
        final_lineage=final_snapshot.get('lineage') or {};source_snapshots=final_lineage.get('sources') or []
        if (len(source_snapshots)!=len(manifest['entries'])
                or [_entry_subtitle_snapshot_hash(entry,row) for entry,row in zip(manifest['entries'],source_snapshots)]!=[
                entry['media'].get('subtitle_snapshot_hash') for entry in manifest['entries']]):
            raise HTTPException(409,'CHAPTER_COMPLETION_SUBTITLE_ORDER_CHANGED')
        if (final_lineage.get('kind')!='merge'
                or [row.get('source_sha256') for row in final_lineage.get('segments') or []]!=expected):
            raise HTTPException(409,'CHAPTER_COMPLETION_SEGMENT_LINEAGE_CHANGED')
        lease.checkpoint(99,'准备原子发布章回视频');lease.stop();heartbeat_metrics=lease.metrics()
        db.rollback();db.expire_all()
        if db.query(Task).filter_by(id=task_id,status='running',claim_token=token,worker_id=worker_id,
                attempt=attempt,metadata_json=encoded).update({'id':task_id},synchronize_session=False)!=1:
            raise HTTPException(409,'CHAPTER_COMPLETION_OWNER_CHANGED')
        if db.query(Chapter).filter_by(id=task.chapter_id,novel_id=task.novel_id).update({
                'id':task.chapter_id},synchronize_session=False)!=1:raise HTTPException(409,'CHAPTER_COMPLETION_PUBLICATION_FENCED')
        from app.models.chapter_shot_split import ShotSource
        for entry in manifest['entries']:
            shot_fence=entry['proof']['fence']['shot']
            if db.query(Shot).filter_by(id=entry['shot_id'],chapter_id=task.chapter_id,
                    index=shot_fence['index'],completion_disposition=shot_fence['completion_disposition'],
                    image_url=shot_fence['image_url'],image_path=shot_fence['image_path'],
                    image_status=shot_fence['image_status'],image_task_id=shot_fence['image_task_id'],
                    video_task_id=shot_fence['video_task_id'],video_status=shot_fence['video_status'],
                    video_url=shot_fence['video_url'],video_director_plan_revision=shot_fence['video_director_plan_revision']).update({
                        'id':entry['shot_id']},synchronize_session=False)!=1:
                raise HTTPException(409,'CHAPTER_COMPLETION_MEMBER_FENCED')
            ownership=entry['ownership']
            if db.query(ShotSource).filter_by(shot_id=entry['shot_id'],run_id=manifest['source']['split_run_id'],
                    source_start=ownership['start'],source_end=ownership['end'],source_hash=ownership['source_hash'],
                    seal=ownership['source_seal']).update({'shot_id':entry['shot_id']},synchronize_session=False)!=1:
                raise HTTPException(409,'CHAPTER_COMPLETION_SOURCE_FENCED')
        final_guard_metrics={};verify_completion_manifest(db,task.novel_id,task.chapter_id,manifest,final_guard_metrics)
        published_snapshot=load_against_receipt(destination,result.get('output_sha256'))
        if (_file_stat(destination)!=result.get('output_stat') or not published_snapshot
                or snapshot_digest(published_snapshot)!=snapshot_digest(final_snapshot)):
            raise HTTPException(409,'CHAPTER_COMPLETION_OUTPUT_CHANGED')
        current=db.get(Task,task_id);url=local_path_to_url(str(destination));degraded=[{
            'shotId':row['shot_id'],'shotIndex':row['shot_index'],'sourceRange':[row['ownership']['start'],row['ownership']['end']]
            } for row in manifest['entries'] if row['kind']=='DEGRADED_NARRATION_CARD']
        receipt={'outcome':'SUCCEEDED_WITH_DEGRADATION' if degraded else 'SUCCEEDED',
            'manifestHash':manifest_hash,'path':str(destination),'url':url,'sha256':result['output_sha256'],
            'bytes':result['output_bytes'],'stat':result['output_stat'],'normalCount':manifest['counts']['normal'],
            'degradedCount':manifest['counts']['degraded'],'degradedRanges':degraded,
            'subtitleSnapshotHash':snapshot_digest(final_snapshot),
            'metrics':{'capture':capture_metrics,'guard':{'preMerge':guard_metrics,'publication':final_guard_metrics},
                'merge':result.get('metrics') or {},
                'heartbeat':heartbeat_metrics}}
        changed=db.query(Chapter).filter_by(id=current.chapter_id,novel_id=current.novel_id,
            final_video=meta.get('previous_final_video'),final_video_task_id=meta.get('previous_final_video_task_id')).update({
                'final_video':url,'final_video_task_id':current.id},synchronize_session=False)
        if changed!=1:raise HTTPException(409,'CHAPTER_COMPLETION_PUBLICATION_REPLACED')
        changed=db.query(Task).filter_by(id=current.id,status='running',claim_token=token,worker_id=worker_id,
            attempt=attempt,metadata_json=encoded).update({
            'status':'completed','progress':100,'result_url':url,'current_step':'章回完整交付已发布',
            'completed_at':datetime.utcnow(),'metadata_json':json.dumps({**meta,'result':receipt},ensure_ascii=False)},synchronize_session=False)
        if changed!=1:raise HTTPException(409,'CHAPTER_COMPLETION_PUBLICATION_FENCED')
        db.commit()
    except Exception as exc:
        if lease:lease.stop()
        db.rollback()
        query=db.query(Task).filter(Task.id==task_id,Task.status.in_(['pending','running']))
        if lease:query=query.filter_by(claim_token=token,worker_id=worker_id,attempt=attempt)
        if encoded is not None:query=query.filter(Task.metadata_json==encoded)
        query.update({'status':'failed','error_message':str(exc),'completed_at':datetime.utcnow()},synchronize_session=False)
        db.commit()
    finally:
        if lease:lease.stop()
        db.close()


def _settle_stale_completion_rows(db,cutoff,before_update=None):
    settled=[]
    tasks=db.query(Task).filter(Task.type=='chapter_video',Task.status=='running',
        (Task.heartbeat_at.is_(None))|(Task.heartbeat_at<cutoff)).order_by(Task.created_at,Task.id).all()
    for task in tasks:
        value=metadata(task)
        if value.get('execution_purpose')!='production' or value.get('delivery_mode')!='CHAPTER_COMPLETION':continue
        observed=task.heartbeat_at
        if before_update:before_update(task)
        query=db.query(Task).filter_by(id=task.id,status='running',claim_token=task.claim_token,
            worker_id=task.worker_id,attempt=task.attempt,metadata_json=task.metadata_json)
        query=query.filter(Task.heartbeat_at.is_(None)) if observed is None else query.filter(
            Task.heartbeat_at==observed,Task.heartbeat_at<cutoff)
        if query.update({'status':'failed','error_message':'CHAPTER_COMPLETION_WORKER_INTERRUPTED_RETRY_EXPLICITLY',
                'completed_at':datetime.utcnow()},synchronize_session=False)==1:settled.append(task.id)
    return settled


def resume_completion_tasks():
    from app.core.database import SessionLocal
    from app.services.background_workers import worker_manager
    db=SessionLocal()
    try:
        tasks=db.query(Task).filter_by(type='chapter_video').filter(Task.status.in_(['pending','running'])).order_by(Task.created_at,Task.id).all()
        pending=[]
        cutoff=datetime.utcnow()-timedelta(minutes=3)
        for task in tasks:
            value=metadata(task)
            if value.get('execution_purpose')!='production' or value.get('delivery_mode')!='CHAPTER_COMPLETION':continue
            if task.status=='pending':
                if value.get('request_hash')!=digest(value.get('request_snapshot')):
                    db.query(Task).filter_by(id=task.id,status='pending',metadata_json=task.metadata_json).update({
                        'status':'failed','error_message':'CHAPTER_COMPLETION_PROOF_REQUIRED',
                        'completed_at':datetime.utcnow()},synchronize_session=False)
                else:pending.append(task.id)
        _settle_stale_completion_rows(db,cutoff)
        db.commit()
    finally:db.close()
    for task_id in pending:worker_manager.worker('chapter_video').enqueue_once(
        task_id,lambda task_id=task_id:run_completion(task_id))


def settle_stale_completion_tasks():
    from app.core.database import SessionLocal
    db=SessionLocal()
    try:
        _settle_stale_completion_rows(db,datetime.utcnow()-timedelta(minutes=3))
        db.commit()
    finally:db.close()


async def run_merge(task_id):
    from app.core.database import SessionLocal
    from app.services.file_storage import file_storage
    from app.utils.path_utils import local_path_to_url
    db = SessionLocal()
    token = str(uuid4())
    try:
        task = db.get(Task, task_id)
        if not task or task.status != 'pending':
            return
        encoded = task.metadata_json
        meta = metadata(task)
        inputs = meta.get('merge_inputs')
        if not isinstance(inputs, dict) or meta.get('input_hash') != digest(inputs):
            raise HTTPException(409, 'LEGACY_VIDEO_MERGE_RETIRED')
        if db.query(Task).filter_by(id=task_id, status='pending', metadata_json=encoded).update({
                'status': 'running', 'claim_token': token, 'started_at': datetime.utcnow(),
                'heartbeat_at': datetime.utcnow(), 'progress': 1, 'current_step': '校验来源并准备章节合并'}, synchronize_session=False) != 1:
            db.rollback(); return
        db.commit()

        def guard(full=True):
            db.expire_all()
            current = db.get(Task, task_id)
            if (not current or current.status != 'running' or current.claim_token != token or current.metadata_json != encoded
                    or current.novel_id != inputs['novel_id'] or current.chapter_id != inputs['chapter_id']):
                raise HTTPException(409, 'MERGE_OWNER_CHANGED')
            if full:
                actual = capture_merge(db, current.novel_id, current.chapter_id, [v['shot_id'] for v in inputs['videos']], inputs['mode'])
                if actual != inputs:
                    raise HTTPException(409, 'MERGE_SOURCE_CHANGED')
            else:
                chapter = db.get(Chapter, current.chapter_id)
                if not chapter or any(v['source_pin']['source_hash'] != source_hash(chapter) for v in inputs['videos']):
                    raise HTTPException(409, 'MERGE_SOURCE_CHANGED')
            return current

        guard()
        directory = file_storage._get_story_dir(task.novel_id) / f'chapter_{task.chapter_id[:8]}' / 'merged-videos' / task_id
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / 'chapter.mp4'

        async def progress(percent, step):
            # Full producer/byte proof is checked before rendering and again at publication.
            # Progress updates fence ownership and source without replaying the full graph.
            current = guard(full=False)
            current.progress, current.current_step, current.heartbeat_at = min(99, int(percent)), step, datetime.utcnow()
            db.commit()

        result = await file_storage.merge_videos([v['path'] for v in inputs['videos']], str(destination), progress_callback=progress)
        if not result.get('success'):
            raise RuntimeError(result.get('message') or 'VIDEO_MERGE_FAILED')
        current = guard()
        url = local_path_to_url(str(destination))
        receipt = {'url': url, 'sha256': file_digest(destination), 'bytes': destination.stat().st_size,
                   'scope': 'REQUESTED_SUBSET', 'is_final_video': False}
        changed = db.query(Task).filter_by(id=task_id, status='running', claim_token=token, metadata_json=encoded).update({
            'status': 'completed', 'progress': 100, 'result_url': url, 'current_step': '可信来源视频合并完成',
            'completed_at': datetime.utcnow(), 'metadata_json': json.dumps({**meta, 'result': receipt}, ensure_ascii=False)}, synchronize_session=False)
        if changed != 1:
            raise HTTPException(409, 'MERGE_PUBLICATION_FENCED')
        db.commit()
    except Exception as exc:
        db.rollback()
        current = db.query(Task).filter_by(id=task_id).populate_existing().first()
        if current and current.status in {'pending', 'running'} and current.claim_token in {None, token}:
            current.status, current.error_message, current.completed_at = 'failed', str(exc), datetime.utcnow()
            db.commit()
    finally:
        db.close()
