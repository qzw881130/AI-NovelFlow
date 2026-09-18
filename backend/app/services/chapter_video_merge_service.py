"""Merge only complete, source-pinned production video receipts; preserve historical files."""
import json
from copy import deepcopy
from datetime import datetime,timedelta
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.services.chapter_asset_parse_service import digest, source_hash
from app.services.runtime_gate import source_pin, validate_video_binding
from app.services.task_execution import metadata, execution_purpose
from app.services.shot_video_execution import completed_video_artifact, file_digest


COMPLETION_VERSION='chapter-completion-manifest-v1'


def video_receipt(db, shot, *, require_subtitle=False):
    pin = source_pin(db, shot.id)
    task = db.get(Task, shot.video_task_id) if shot.video_task_id else None
    if not task or task.type != 'shot_video' or task.status != 'completed' or execution_purpose(task) != 'production':
        raise HTTPException(409, 'VERIFIED_SHOT_VIDEO_REQUIRED')
    data = metadata(task)
    validate_video_binding(db, task, data.get('rsa_binding'))
    verified = completed_video_artifact(db, task.id, shot_id=shot.id)
    if not verified['success']:
        raise HTTPException(409, verified['message'])
    run = data.get('video_run') or {}
    result = run.get('result') or {}
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
    if not path.is_file() or path.stat().st_size != result['bytes'] or file_digest(path) != result['sha256']:
        raise HTTPException(409, 'VIDEO_RESULT_BYTES_CHANGED')
    from app.services.rendered_subtitles import load
    subtitle_snapshot=load(path)
    if require_subtitle and (not subtitle_snapshot or subtitle_snapshot.get('unavailable')
            or result.get('subtitle_snapshot_hash')!=digest(subtitle_snapshot)):
        raise HTTPException(409,'VIDEO_SUBTITLE_LINEAGE_REQUIRED')
    return {'shot_id': shot.id, 'source_pin': pin, 'task_id': task.id, 'run_id': run['run_id'],
            'rsa_binding': data['rsa_binding'], 'path': str(path), 'sha256': result['sha256'],
            'subtitle_snapshot_hash':digest(subtitle_snapshot) if subtitle_snapshot and not subtitle_snapshot.get('unavailable') else None,
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


def capture_completion(db,novel_id,chapter_id):
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).populate_existing().first()
    if not chapter:raise HTTPException(404,'章回不存在')
    shots=db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index,Shot.id).all()
    if not shots or [shot.index for shot in shots]!=list(range(1,len(shots)+1)):
        raise HTTPException(409,'CHAPTER_COMPLETION_SHOT_ORDER_INVALID')
    entries=[];cursor=0;split_run_id=None;current_source_hash=source_hash(chapter)
    for ordinal,shot in enumerate(shots,1):
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
            media=video_receipt(db,shot,require_subtitle=True);kind='NORMAL_VIDEO'
        elif disposition=='DEGRADED_NARRATION_CARD':
            from app.services.narration_card_service import completed_artifact
            media=completed_artifact(db,shot);kind='DEGRADED_NARRATION_CARD'
        else:raise HTTPException(409,'CHAPTER_COMPLETION_DISPOSITION_UNSUPPORTED')
        entries.append({'ordinal':ordinal,'kind':kind,'shot_id':shot.id,'shot_index':shot.index,
            'ownership':ownership,'media':media})
    if chapter.content[cursor:].strip():raise HTTPException(409,'CHAPTER_COMPLETION_SOURCE_GAP')
    normal=sum(row['kind']=='NORMAL_VIDEO' for row in entries);degraded=len(entries)-normal
    manifest={'version':COMPLETION_VERSION,'novel_id':novel_id,'chapter_id':chapter_id,
        'source':{'split_run_id':split_run_id,'source_hash':current_source_hash,
            'length_codepoints':len(chapter.content),'offset_unit':'UNICODE_CODE_POINT'},
        'entries':entries,'counts':{'normal':normal,'degraded':degraded,'total':len(entries)}}
    return manifest


def completion_readiness(db,novel_id,chapter_id):
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).first()
    if not chapter:raise HTTPException(404,'章回不存在')
    shots=db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index,Shot.id).all();rows=[]
    for shot in shots:
        disposition=getattr(shot,'completion_disposition','NORMAL') or 'NORMAL';blocker=None
        try:
            if disposition=='NORMAL':video_receipt(db,shot)
            elif disposition=='DEGRADED_NARRATION_CARD':
                from app.services.narration_card_service import completed_artifact
                completed_artifact(db,shot)
            else:raise HTTPException(409,'CHAPTER_COMPLETION_DISPOSITION_UNSUPPORTED')
        except HTTPException as exc:blocker=exc.detail
        source=shot.source_record
        rows.append({'shotId':shot.id,'shotIndex':shot.index,'completionDisposition':disposition,
            'sourceRange':[source.source_start,source.source_end] if source else None,'ready':blocker is None,'blocker':blocker})
    manifest=None;blocker=None
    try:manifest=capture_completion(db,novel_id,chapter_id)
    except HTTPException as exc:blocker=exc.detail
    return {'ready':manifest is not None,'manifestHash':digest(manifest) if manifest else None,
        'counts':manifest['counts'] if manifest else {'normal':sum(r['completionDisposition']=='NORMAL' for r in rows),
            'degraded':sum(r['completionDisposition']=='DEGRADED_NARRATION_CARD' for r in rows),'total':len(rows)},
        'entries':rows,'blocker':blocker}


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
        if capture_completion(db,novel_id,chapter_id)!=manifest:return None
    except HTTPException:return None
    from app.services.rendered_subtitles import load
    from app.utils.path_utils import local_path_to_url,url_to_local_path
    path=Path(result.get('path') or url_to_local_path(chapter.final_video) or '')
    snapshot=load(path) if path.is_file() else None
    degraded=[{'shotId':row['shot_id'],'shotIndex':row['shot_index'],
        'sourceRange':[row['ownership']['start'],row['ownership']['end']]}
        for row in manifest['entries'] if row['kind']=='DEGRADED_NARRATION_CARD']
    expected_result={'outcome':'SUCCEEDED_WITH_DEGRADATION' if degraded else 'SUCCEEDED',
        'manifestHash':meta['manifest_hash'],'path':str(path),'url':chapter.final_video,
        'normalCount':manifest['counts']['normal'],'degradedCount':manifest['counts']['degraded'],
        'degradedRanges':degraded}
    if (not path.is_file() or path.stat().st_size!=result.get('bytes') or file_digest(path)!=result.get('sha256')
            or not snapshot or snapshot.get('unavailable') or digest(snapshot)!=result.get('subtitleSnapshotHash')):
        return None
    lineage=snapshot.get('lineage') or {};expected_media=[entry['media']['sha256'] for entry in manifest['entries']]
    if (lineage.get('kind')!='merge'
            or [row.get('source_sha256') for row in lineage.get('segments') or []]!=expected_media
            or [digest(row) for row in lineage.get('sources') or []]!=[
                entry['media'].get('subtitle_snapshot_hash') for entry in manifest['entries']]):return None
    if (task.result_url!=chapter.final_video or local_path_to_url(str(path))!=chapter.final_video
            or any(result.get(key)!=value for key,value in expected_result.items())):return None
    return {'taskId':task.id,**deepcopy(result)}


async def run_completion(task_id):
    from app.core.database import SessionLocal
    from app.services.file_storage import file_storage
    from app.utils.path_utils import local_path_to_url
    db=SessionLocal();token=str(uuid4())
    try:
        task=db.get(Task,task_id)
        if not task or task.status!='pending':return
        encoded=task.metadata_json;meta=metadata(task);manifest=meta.get('completion_manifest')
        if (not isinstance(manifest,dict) or meta.get('manifest_hash')!=digest(manifest)
                or meta.get('execution_purpose')!='production' or meta.get('delivery_mode')!='CHAPTER_COMPLETION'):
            raise HTTPException(409,'CHAPTER_COMPLETION_MANIFEST_INVALID')
        if db.query(Task).filter_by(id=task.id,status='pending',metadata_json=encoded).update({
                'status':'running','claim_token':token,'started_at':datetime.utcnow(),'heartbeat_at':datetime.utcnow(),
                'progress':1,'current_step':'校验 Chapter Completion Manifest'},synchronize_session=False)!=1:
            db.rollback();return
        db.commit()
        def guard():
            db.expire_all();current=db.get(Task,task_id)
            if (not current or current.status!='running' or current.claim_token!=token or current.metadata_json!=encoded):
                raise HTTPException(409,'CHAPTER_COMPLETION_OWNER_CHANGED')
            if capture_completion(db,current.novel_id,current.chapter_id)!=manifest:
                raise HTTPException(409,'CHAPTER_COMPLETION_SOURCE_CHANGED')
            return current
        guard();directory=file_storage._get_story_dir(task.novel_id)/f'chapter_{task.chapter_id[:8]}'/'completion'/task.id
        directory.mkdir(parents=True,exist_ok=True);destination=directory/'chapter.mp4'
        async def progress(percent,step):
            changed=db.query(Task).filter_by(id=task_id,status='running',claim_token=token,metadata_json=encoded).update({
                'heartbeat_at':datetime.utcnow(),'progress':min(99,int(percent)),'current_step':step},synchronize_session=False)
            if changed!=1:raise HTTPException(409,'CHAPTER_COMPLETION_OWNER_CHANGED')
            db.commit()
        result=await file_storage.merge_videos([entry['media']['path'] for entry in manifest['entries']],str(destination),
            progress_callback=progress)
        if not result.get('success'):raise RuntimeError(result.get('message') or 'CHAPTER_COMPLETION_MERGE_FAILED')
        expected=[entry['media']['sha256'] for entry in manifest['entries']]
        if [row.get('source_sha256') for row in result.get('media_segments') or []]!=expected:
            raise HTTPException(409,'CHAPTER_COMPLETION_MEDIA_ORDER_CHANGED')
        from app.services.rendered_subtitles import load
        final_snapshot=load(destination)
        if not final_snapshot or final_snapshot.get('unavailable'):
            raise HTTPException(409,'CHAPTER_COMPLETION_SUBTITLE_LINEAGE_REQUIRED')
        final_lineage=final_snapshot.get('lineage') or {};source_snapshots=final_lineage.get('sources') or []
        if ([digest(row) for row in source_snapshots]!=[
                entry['media'].get('subtitle_snapshot_hash') for entry in manifest['entries']]):
            raise HTTPException(409,'CHAPTER_COMPLETION_SUBTITLE_ORDER_CHANGED')
        if (final_lineage.get('kind')!='merge'
                or [row.get('source_sha256') for row in final_lineage.get('segments') or []]!=expected):
            raise HTTPException(409,'CHAPTER_COMPLETION_SEGMENT_LINEAGE_CHANGED')
        if db.query(Chapter).filter_by(id=task.chapter_id,novel_id=task.novel_id).update({
                'id':task.chapter_id},synchronize_session=False)!=1:
            raise HTTPException(409,'CHAPTER_COMPLETION_PUBLICATION_FENCED')
        for entry in manifest['entries']:
            if db.query(Shot).filter_by(id=entry['shot_id'],chapter_id=task.chapter_id).update({
                    'id':entry['shot_id']},synchronize_session=False)!=1:
                raise HTTPException(409,'CHAPTER_COMPLETION_MEMBER_FENCED')
        db.expire_all();current=guard();url=local_path_to_url(str(destination));degraded=[{
            'shotId':row['shot_id'],'shotIndex':row['shot_index'],'sourceRange':[row['ownership']['start'],row['ownership']['end']]
            } for row in manifest['entries'] if row['kind']=='DEGRADED_NARRATION_CARD']
        receipt={'outcome':'SUCCEEDED_WITH_DEGRADATION' if degraded else 'SUCCEEDED',
            'manifestHash':meta['manifest_hash'],'path':str(destination),'url':url,'sha256':file_digest(destination),
            'bytes':destination.stat().st_size,'normalCount':manifest['counts']['normal'],
            'degradedCount':manifest['counts']['degraded'],'degradedRanges':degraded,
            'subtitleSnapshotHash':digest(final_snapshot)}
        changed=db.query(Chapter).filter_by(id=current.chapter_id,novel_id=current.novel_id,
            final_video=meta.get('previous_final_video'),final_video_task_id=meta.get('previous_final_video_task_id')).update({
                'final_video':url,'final_video_task_id':current.id},synchronize_session=False)
        if changed!=1:raise HTTPException(409,'CHAPTER_COMPLETION_PUBLICATION_REPLACED')
        changed=db.query(Task).filter_by(id=current.id,status='running',claim_token=token,metadata_json=encoded).update({
            'status':'completed','progress':100,'result_url':url,'current_step':'章回完整交付已发布',
            'completed_at':datetime.utcnow(),'metadata_json':json.dumps({**meta,'result':receipt},ensure_ascii=False)},synchronize_session=False)
        if changed!=1:raise HTTPException(409,'CHAPTER_COMPLETION_PUBLICATION_FENCED')
        db.commit()
    except Exception as exc:
        db.rollback();current=db.query(Task).filter_by(id=task_id).populate_existing().first()
        if current and current.status in {'pending','running'} and current.claim_token in {None,token}:
            current.status,current.error_message,current.completed_at='failed',str(exc),datetime.utcnow();db.commit()
    finally:db.close()


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
            if task.status=='running':
                if task.heartbeat_at and task.heartbeat_at>=cutoff:continue
                db.query(Task).filter_by(id=task.id,status='running',claim_token=task.claim_token,
                    metadata_json=task.metadata_json).update({'status':'failed','error_message':'CHAPTER_COMPLETION_WORKER_INTERRUPTED_RETRY_EXPLICITLY',
                        'completed_at':datetime.utcnow()},synchronize_session=False)
            else:pending.append(task.id)
        db.commit()
    finally:db.close()
    for task_id in pending:worker_manager.worker('chapter_video').enqueue(lambda task_id=task_id:run_completion(task_id))


def settle_stale_completion_tasks():
    from app.core.database import SessionLocal
    db=SessionLocal()
    try:
        cutoff=datetime.utcnow()-timedelta(minutes=3)
        for task in db.query(Task).filter(Task.type=='chapter_video',Task.status=='running',
                (Task.heartbeat_at.is_(None))|(Task.heartbeat_at<cutoff)).all():
            value=metadata(task)
            if value.get('execution_purpose')!='production' or value.get('delivery_mode')!='CHAPTER_COMPLETION':continue
            db.query(Task).filter_by(id=task.id,status='running',claim_token=task.claim_token,
                metadata_json=task.metadata_json).update({'status':'failed','error_message':'CHAPTER_COMPLETION_WORKER_INTERRUPTED_RETRY_EXPLICITLY',
                    'completed_at':datetime.utcnow()},synchronize_session=False)
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
