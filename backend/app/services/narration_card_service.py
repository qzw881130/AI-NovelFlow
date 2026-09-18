"""Formal AudioDrive-backed, model-free video producer for R-CD1 narration cards."""
from datetime import datetime,timedelta
import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.audio_drive import AudioEventTTSAsset,ShotAudioTimeline,ShotAudioTimelineEvent
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.repositories.audio_drive import AudioDriveRepository
from app.services.chapter_asset_parse_service import digest
from app.services.controlled_degradation_service import DISPOSITION,load_policy
from app.services.file_storage import file_storage
from app.services.rendered_subtitles import fingerprint,load
from app.services.runtime_gate import source_pin,validate_source_pin
from app.utils.path_utils import local_path_to_url


TASK_TYPE='narration_card_video'


def capture(db,shot_id):
    shot=db.query(Shot).filter_by(id=shot_id).populate_existing().first()
    if not shot:raise HTTPException(404,'分镜不存在')
    if getattr(shot,'completion_disposition','NORMAL')!=DISPOSITION:
        raise HTTPException(409,'NARRATION_CARD_REQUIRED')
    pin=source_pin(db,shot.id);source=shot.source_record
    bindings=source.bindings or {}
    if any(bindings.get(kind) for kind in ('characters','scenes','props')):
        raise HTTPException(409,'NARRATION_CARD_VISUAL_BINDING_FORBIDDEN')
    events=AudioDriveRepository(db).list_events(shot.id)
    if (len(events)!=1 or events[0].event_type!='NARRATION' or events[0].voice_owner_name!='旁白'
            or events[0].voice_owner_character_id is not None or events[0].visible_speaker_name is not None
            or events[0].visible_speaker_character_id is not None or events[0].requires_visible_lipsync
            or events[0].text!=source.ranges[0]['text']):
        raise HTTPException(409,'NARRATION_CARD_EXACT_EVENT_REQUIRED')
    timeline=db.query(ShotAudioTimeline).filter_by(shot_id=shot.id,status='READY').order_by(
        ShotAudioTimeline.revision.desc(),ShotAudioTimeline.id.desc()).first()
    if not timeline:raise HTTPException(409,'NARRATION_CARD_AUDIO_TIMELINE_REQUIRED')
    summary=json.loads(timeline.audio_summary_json or '{}')
    if summary.get('source_pin')!=pin:raise HTTPException(409,'NARRATION_CARD_AUDIO_TIMELINE_STALE')
    timeline_events=db.query(ShotAudioTimelineEvent).filter_by(timeline_id=timeline.id).order_by(
        ShotAudioTimelineEvent.event_order).all()
    timeline_event=timeline_events[0] if len(timeline_events)==1 else None
    tts=db.get(AudioEventTTSAsset,timeline_event.tts_asset_id) if timeline_event and timeline_event.tts_asset_id else None
    if (not timeline_event or timeline_event.audio_event_id!=events[0].id or timeline_event.event_type!='NARRATION'
            or timeline_event.requires_visible_lipsync or not tts or tts.status!='READY' or not tts.is_current
            or events[0].tts_status!='READY' or tts.audio_event_id!=events[0].id):
        raise HTTPException(409,'NARRATION_CARD_FORMAL_TTS_TIMELINE_REQUIRED')
    from app.services.audio_drive_service import AudioDriveService,_reconciled_audio_windows
    audio_service=AudioDriveService(db)
    config=json.loads(tts.config_json or '{}');producer=db.get(Task,config.get('task_id')) if config.get('task_id') else None
    remote=config.get('remote_proof') or {};remote_status=remote.get('status') or {}
    remote_workflow=remote.get('submitted_workflow') or {};text_node=remote_workflow.get(str(remote.get('text_node_id') or ''))
    text_inputs=text_node.get('inputs') if isinstance(text_node,dict) else {};text_field=remote.get('text_input_field')
    producer_meta=json.loads(producer.metadata_json or '{}') if producer else {}
    tts_snapshot=load(tts.audio_path) if tts.audio_path else None
    expected_text_hash=audio_service._hash_payload({'text':events[0].text})
    if (not audio_service._tts_asset_eligible(events[0],tts,pin) or not producer
            or producer.status!='completed' or producer.type!='audio_event_tts' or producer.shot_id!=shot.id
            or producer.novel_id!=shot.chapter.novel_id or producer.chapter_id!=shot.chapter_id
            or producer.character_id!=config.get('voice_binding',{}).get('character_id')
            or producer.result_url!=tts.audio_url
            or producer_meta.get('execution_purpose')!='production' or producer_meta.get('audio_event_id')!=events[0].id
            or producer_meta.get('source_pin')!=pin or producer_meta.get('voice_binding')!=config.get('voice_binding')
            or config.get('source_pin')!=pin or config.get('emotion_prompt')!=events[0].emotion_prompt
            or not remote.get('prompt_id') or remote.get('submitted_text')!=events[0].text
            or not isinstance(remote.get('submitted_workflow'),dict)
            or remote.get('submitted_workflow_hash')!=audio_service._hash_payload(remote.get('submitted_workflow'))
            or text_field not in {'text','prompt','value'} or text_inputs.get(text_field)!=events[0].text
            or not remote.get('save_audio_node_id') or remote.get('output_node_id')!=remote.get('save_audio_node_id')
            or not remote.get('output') or not remote.get('history')
            or not (remote_status.get('completed') or remote_status.get('status_str') in {'success','completed'})
            or tts.text_hash!=expected_text_hash or not tts_snapshot or tts_snapshot.get('unavailable')
            or tts_snapshot.get('lineage',{}).get('kind')!='tts'
            or tts_snapshot.get('lineage',{}).get('audio_event_id')!=events[0].id
            or tts_snapshot.get('lineage',{}).get('tts_asset_id')!=tts.id
            or tts_snapshot.get('lineage',{}).get('task_id')!=producer.id
            or tts_snapshot.get('lineage',{}).get('text_hash')!=expected_text_hash
            or len(tts_snapshot.get('cues') or [])!=1 or tts_snapshot['cues'][0].get('text')!=events[0].text):
        raise HTTPException(409,'NARRATION_CARD_TTS_PRODUCER_PROOF_REQUIRED')
    if (not tts.audio_path or not Path(tts.audio_path).is_file() or not tts.content_hash
            or fingerprint(tts.audio_path)!=tts.content_hash or Path(tts.audio_path).stat().st_size!=tts.file_size):
        raise HTTPException(409,'NARRATION_CARD_TTS_BYTES_CHANGED')
    plan=json.loads(shot.video_director_plan or '{}')
    try:windows=_reconciled_audio_windows(plan)
    except ValueError as exc:raise HTTPException(409,'NARRATION_CARD_AUDIO_WINDOW_INVALID') from exc
    if len(windows)!=1:raise HTTPException(409,'NARRATION_CARD_SINGLE_AUDIO_WINDOW_REQUIRED')
    window=windows[0];audio_path=window.get('final_audio_path')
    if (window.get('audio_status')!='READY' or not audio_path or not Path(audio_path).is_file()
            or float(window.get('start_time') or 0)!=0):
        raise HTTPException(409,'NARRATION_CARD_FINAL_AUDIO_REQUIRED')
    audio_snapshot=load(audio_path)
    lineage=audio_snapshot.get('lineage') if audio_snapshot else {}
    manifest_path=window.get('clip_audio_manifest_path');manifest=None
    try:manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8')) if manifest_path else None
    except (OSError,ValueError,TypeError):manifest=None
    final_segments=(manifest or {}).get('final_segments') or []
    lineage_segments=lineage.get('segments') or []
    source_levels=((manifest or {}).get('render_metadata') or {}).get('sourceLevels') or []
    audio_receipt=window.get('audio_receipt');actual_receipt={'manifest_hash':digest(manifest) if isinstance(manifest,dict) else None,
        'drive_audio_sha256':manifest.get('drive_audio_sha256') if isinstance(manifest,dict) else None,
        'drive_audio_bytes':manifest.get('drive_audio_bytes') if isinstance(manifest,dict) else None,
        'final_audio_sha256':fingerprint(audio_path),'final_audio_bytes':Path(audio_path).stat().st_size,
        'final_audio_snapshot_hash':digest(audio_snapshot) if audio_snapshot else None}
    if (not audio_snapshot or audio_snapshot.get('unavailable') or len(audio_snapshot.get('cues') or [])!=1
            or audio_snapshot['cues'][0].get('text')!=events[0].text
            or audio_snapshot['cues'][0].get('audio_event_id')!=events[0].id
            or audio_snapshot['cues'][0].get('tts_asset_id')!=tts.id
            or lineage.get('kind')!='clip_audio' or lineage.get('timeline_id')!=timeline.id
            or lineage.get('timeline_revision')!=timeline.revision or lineage.get('timeline_hash')!=timeline.generated_from_hash
            or lineage.get('window_index')!=1 or float(lineage.get('clip_start') or 0)!=0
            or not isinstance(manifest,dict) or audio_receipt!=actual_receipt
            or manifest.get('source_pin')!=pin or manifest.get('shot_id')!=shot.id
            or manifest.get('window_index')!=1 or manifest.get('audio_timeline_id')!=timeline.id
            or manifest.get('audio_timeline_revision')!=timeline.revision
            or manifest.get('audio_timeline_hash')!=timeline.generated_from_hash
            or str(Path(manifest.get('final_audio_path') or '').resolve())!=str(Path(audio_path).resolve())
            or len(final_segments)!=1 or len(lineage_segments)!=1 or len(source_levels)!=1
            or final_segments!=lineage_segments or manifest.get('render_metadata')!=lineage.get('render_metadata')
            or any(segment.get('audio_event_id')!=events[0].id or segment.get('tts_asset_id')!=tts.id
                   or str(Path(segment.get('source_path') or '').resolve())!=str(Path(tts.audio_path).resolve())
                   or segment.get('source_sha256')!=tts.content_hash
                   or float(segment.get('source_start') or 0)!=0
                   or abs(float(segment.get('clip_start') or 0)-float(timeline_event.start_time))>0.001
                   or abs(float(segment.get('duration') or 0)-(
                       float(timeline_event.end_time)-float(timeline_event.start_time)))>0.001
                   or segment.get('event_order')!=timeline_event.event_order
                   or segment.get('voice_owner_name')!='旁白'
                   or segment.get('visible_speaker_name') is not None
                   or bool(segment.get('requires_visible_lipsync')) for segment in (final_segments+lineage_segments))
            or source_levels[0].get('audioEventId')!=events[0].id
            or source_levels[0].get('ttsAssetId')!=tts.id or source_levels[0].get('sourceSha256')!=tts.content_hash):
        raise HTTPException(409,'NARRATION_CARD_AUDIO_SOURCE_PROOF_REQUIRED')
    duration=float(window.get('end_time') or timeline.total_duration or 0)
    if (duration<=0 or abs(float(window.get('start_time') or 0))>0.001
            or abs(duration-float(timeline.total_duration or 0))>0.001
            or float(timeline_event.end_time or 0)>duration):
        raise HTTPException(409,'NARRATION_CARD_DURATION_INVALID')
    measured=AudioDriveService._probe_audio_duration(str(audio_path))
    cue_end=float(audio_snapshot['cues'][0].get('end') or 0)
    if (not measured or abs(measured-duration)>0.05 or cue_end>measured+0.001
            or abs(float(manifest.get('clip_duration') or 0)-duration)>0.001):
        raise HTTPException(409,'NARRATION_CARD_AUDIO_DURATION_MISMATCH')
    policy=load_policy()
    return {'version':'narration-card-input-v1','shot_id':shot.id,'chapter_id':shot.chapter_id,
        'novel_id':shot.chapter.novel_id,'source_pin':pin,'source_range':[source.source_start,source.source_end],
        'source_text_hash':digest(events[0].text),'audio_event_id':events[0].id,
        'tts_asset_id':tts.id,'timeline':{'id':timeline.id,'revision':timeline.revision,'hash':timeline.generated_from_hash},
        'audio':{'path':str(Path(audio_path).resolve()),'sha256':fingerprint(audio_path),
            'snapshot_hash':digest(audio_snapshot),'manifest_path':str(Path(manifest_path).resolve()),
            'manifest_hash':digest(manifest),'duration':duration},
        'policy':policy,'render_profile':policy['definition']['render']}


def completed_artifact(db,shot):
    if getattr(shot,'completion_disposition','NORMAL')!=DISPOSITION or not shot.video_task_id:
        raise HTTPException(409,'NARRATION_CARD_VIDEO_REQUIRED')
    task=db.get(Task,shot.video_task_id);meta=json.loads(task.metadata_json or '{}') if task else {}
    inputs=meta.get('inputs');result=meta.get('result')
    if (not task or task.type!=TASK_TYPE or task.status!='completed' or task.shot_id!=shot.id
            or meta.get('execution_purpose')!='production' or meta.get('delivery_mode')!='NARRATION_CARD'
            or digest(inputs)!=meta.get('input_hash')
            or inputs!=capture(db,shot.id) or not isinstance(result,dict)
            or result.get('url')!=shot.video_url or result.get('path') is None):
        raise HTTPException(409,'NARRATION_CARD_VIDEO_RECEIPT_INVALID')
    path=Path(result['path'])
    snapshot=load(path) if path.is_file() else None
    if (not path.is_file() or path.stat().st_size!=result.get('bytes') or fingerprint(path)!=result.get('sha256')
            or not snapshot or snapshot.get('unavailable') or digest(snapshot)!=result.get('subtitle_snapshot_hash')
            or snapshot.get('lineage',{}).get('input_hash')!=meta.get('input_hash')
            or snapshot.get('lineage',{}).get('shot_id')!=shot.id
            or snapshot.get('lineage',{}).get('source_pin')!=inputs.get('source_pin')
            or snapshot.get('lineage',{}).get('timeline')!=inputs.get('timeline')
            or snapshot.get('lineage',{}).get('source_audio_sha256')!=inputs.get('audio',{}).get('sha256')
            or digest(snapshot.get('lineage',{}).get('source_audio_snapshot'))!=inputs.get('audio',{}).get('snapshot_hash')):
        raise HTTPException(409,'NARRATION_CARD_VIDEO_BYTES_CHANGED')
    return {'shot_id':shot.id,'shot_index':shot.index,'task_id':task.id,'path':str(path),'url':shot.video_url,
        'sha256':result['sha256'],'bytes':result['bytes'],'duration':result['duration'],
        'frames':result['frames'],'input_hash':meta['input_hash'],'source_pin':inputs['source_pin'],
        'source_range':inputs['source_range'],'source_text_hash':inputs['source_text_hash'],
        'subtitle_snapshot_hash':digest(snapshot)}


def prepare_audio(db,shot_id,*,force_tts=False):
    shot=db.get(Shot,shot_id)
    if not shot or getattr(shot,'completion_disposition','NORMAL')!=DISPOSITION:
        raise HTTPException(409,'NARRATION_CARD_REQUIRED')
    from app.services.audio_drive_service import AudioDriveService
    policy=load_policy()['definition']
    return AudioDriveService(db).create_audio_prepare_task([shot_id],
        max_clip_duration=policy['audio_max_clip_duration'],force_tts=True,force_clip_audio=True)


def create_render_task(db,shot_id):
    if db.query(Shot).filter_by(id=shot_id).update({'id':shot_id},synchronize_session=False)!=1:
        raise HTTPException(404,'分镜不存在')
    db.expire_all();inputs=capture(db,shot_id);shot=db.get(Shot,shot_id)
    if shot.video_task_id:
        try:return {'taskId':shot.video_task_id,'status':'completed','skipped':True,
            'artifact':completed_artifact(db,shot)}
        except HTTPException:pass
    active=db.query(Task).filter_by(type=TASK_TYPE,shot_id=shot.id).filter(Task.status.in_(['pending','running'])).first()
    if active:raise HTTPException(409,'NARRATION_CARD_TASK_ACTIVE')
    task=Task(id=str(uuid4()),type=TASK_TYPE,status='pending',novel_id=inputs['novel_id'],chapter_id=shot.chapter_id,
        shot_id=shot.id,name=f'NARRATION_CARD · Shot {shot.index}',description='生成 deterministic neutral narration card',
        progress=0,current_step='等待渲染',metadata_json=json.dumps({'execution_purpose':'production','delivery_mode':'NARRATION_CARD',
            'inputs':inputs,'input_hash':digest(inputs)},ensure_ascii=False))
    db.add(task);shot.video_task_id=task.id;shot.video_status='generating';db.commit()
    from app.services.background_workers import worker_manager
    worker_manager.worker(TASK_TYPE).enqueue(lambda:run_render(task.id))
    return {'taskId':task.id,'status':task.status,'skipped':False}


def resume_pending_render_tasks():
    db=SessionLocal()
    try:
        cutoff=datetime.utcnow()-timedelta(minutes=3)
        for task in db.query(Task).filter(Task.type==TASK_TYPE,Task.status=='running',
                (Task.heartbeat_at.is_(None))|(Task.heartbeat_at<cutoff)).all():
            changed=db.query(Task).filter_by(id=task.id,status='running',claim_token=task.claim_token,
                metadata_json=task.metadata_json).update({'status':'failed','error_message':'NARRATION_CARD_WORKER_INTERRUPTED_RETRY_EXPLICITLY',
                    'completed_at':datetime.utcnow()},synchronize_session=False)
            if changed:db.query(Shot).filter_by(id=task.shot_id,video_task_id=task.id,video_status='generating').update({
                'video_status':'failed'},synchronize_session=False)
        pending=[task.id for task in db.query(Task).filter_by(type=TASK_TYPE,status='pending').order_by(Task.created_at,Task.id)]
        db.commit()
    finally:db.close()
    from app.services.background_workers import worker_manager
    for task_id in pending:worker_manager.worker(TASK_TYPE).enqueue(lambda task_id=task_id:run_render(task_id))


def settle_stale_render_tasks():
    db=SessionLocal()
    try:
        cutoff=datetime.utcnow()-timedelta(minutes=3)
        for task in db.query(Task).filter(Task.type==TASK_TYPE,Task.status=='running',
                (Task.heartbeat_at.is_(None))|(Task.heartbeat_at<cutoff)).all():
            changed=db.query(Task).filter_by(id=task.id,status='running',claim_token=task.claim_token,
                metadata_json=task.metadata_json).update({'status':'failed','error_message':'NARRATION_CARD_WORKER_INTERRUPTED_RETRY_EXPLICITLY',
                    'completed_at':datetime.utcnow()},synchronize_session=False)
            if changed:db.query(Shot).filter_by(id=task.shot_id,video_task_id=task.id,video_status='generating').update({
                'video_status':'failed'},synchronize_session=False)
        db.commit()
    finally:db.close()


async def run_render(task_id):
    db=SessionLocal();token=str(uuid4())
    try:
        task=db.get(Task,task_id)
        if not task or task.type!=TASK_TYPE or task.status!='pending':return
        encoded=task.metadata_json;meta=json.loads(encoded or '{}');inputs=meta.get('inputs')
        if digest(inputs)!=meta.get('input_hash'):raise RuntimeError('NARRATION_CARD_INPUT_HASH_CHANGED')
        changed=db.query(Task).filter_by(id=task.id,status='pending',metadata_json=encoded).update({
            'status':'running','claim_token':token,'started_at':datetime.utcnow(),'heartbeat_at':datetime.utcnow(),
            'progress':5,'current_step':'验证 narration card 输入'},synchronize_session=False)
        if changed!=1:db.rollback();return
        db.commit();db.expire_all()
        if capture(db,inputs['shot_id'])!=inputs:raise RuntimeError('NARRATION_CARD_INPUT_CHANGED')
        attempt=uuid4().hex;path=file_storage.get_narration_card_video_path(
            inputs['novel_id'],inputs['chapter_id'],inputs['shot_id'],attempt)
        lineage={'version':'narration-card-lineage-v1','input_hash':meta['input_hash'],
            'shot_id':inputs['shot_id'],'source_pin':inputs['source_pin'],'source_range':inputs['source_range'],
            'source_text_hash':inputs['source_text_hash'],'audio_event_id':inputs['audio_event_id'],
            'timeline':inputs['timeline']}
        async def progress(seconds):
            percent=min(90,max(10,int(10+80*seconds/max(inputs['audio']['duration'],0.001))))
            changed=db.query(Task).filter_by(id=task_id,status='running',claim_token=token,metadata_json=encoded).update({
                'heartbeat_at':datetime.utcnow(),'progress':percent,'current_step':'渲染 deterministic narration card'},synchronize_session=False)
            if changed!=1:raise RuntimeError('NARRATION_CARD_OWNER_CHANGED')
            db.commit()
        result=await file_storage.render_narration_card(inputs['audio']['path'],str(path),
            inputs['audio']['duration'],inputs['render_profile'],lineage,
            expected_audio_sha256=inputs['audio']['sha256'],expected_snapshot_hash=inputs['audio']['snapshot_hash'],
            progress_callback=progress)
        if not result.get('success'):raise RuntimeError(result.get('message') or 'NARRATION_CARD_RENDER_FAILED')
        if db.query(Shot).filter_by(id=inputs['shot_id'],video_task_id=task_id).update({
                'id':inputs['shot_id']},synchronize_session=False)!=1:
            raise RuntimeError('NARRATION_CARD_PUBLICATION_FENCED')
        db.expire_all();task=db.get(Task,task_id);shot=db.get(Shot,inputs['shot_id'])
        if (not task or task.status!='running' or task.claim_token!=token or task.metadata_json!=encoded or not shot
                or shot.video_task_id!=task.id or capture(db,shot.id)!=inputs):
            raise RuntimeError('NARRATION_CARD_PUBLICATION_FENCED')
        publication={'path':result['output_path'],'url':local_path_to_url(result['output_path']),
            'sha256':result['sha256'],'bytes':result['bytes'],'duration':result['duration'],
            'frames':result['frames'],'subtitle_snapshot_hash':digest(result['subtitle_snapshot'])}
        if db.query(Shot).filter_by(id=shot.id,video_task_id=task.id,video_status='generating').update({
                'video_url':publication['url'],'video_status':'completed'},synchronize_session=False)!=1:
            raise RuntimeError('NARRATION_CARD_PUBLICATION_FENCED')
        if db.query(Task).filter_by(id=task.id,status='running',claim_token=token,metadata_json=encoded).update({
                'status':'completed','progress':100,'current_step':'NARRATION_CARD 已发布',
                'result_url':publication['url'],'completed_at':datetime.utcnow(),
                'metadata_json':json.dumps({**meta,'result':publication},ensure_ascii=False)},synchronize_session=False)!=1:
            raise RuntimeError('NARRATION_CARD_PUBLICATION_FENCED')
        db.query(Chapter).filter_by(id=shot.chapter_id).update({'final_video':None,'final_video_task_id':None},synchronize_session=False)
        db.commit()
    except Exception as exc:
        db.rollback();task=db.get(Task,task_id)
        if task and task.status in {'pending','running'}:
            task.status='failed';task.error_message=str(exc);task.current_step='NARRATION_CARD 失败';task.completed_at=datetime.utcnow()
            shot=db.get(Shot,task.shot_id) if task.shot_id else None
            if shot and shot.video_task_id==task.id:shot.video_status='failed'
            db.commit()
    finally:db.close()
