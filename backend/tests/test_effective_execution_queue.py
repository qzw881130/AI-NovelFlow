"""Frozen continuation policy through the existing durable queue and scheduler."""
import asyncio
from copy import deepcopy
import json

import pytest
from sqlalchemy.orm import sessionmaker
from app.models.background_job import BackgroundJob
from app.models.task import Task
from app.services import shot_video_service as video
from app.services.task_service import TaskService
from app.services.background_workers import WorkerManager
from app.services.effective_execution import project_effective_execution, projection_record
from test_persistent_shot_video_retry import setup_retry, install_handler, drained
from test_continuous_clip_native_av import persistence


def freeze_policy(db,task,shot,options):
    plan=json.loads(shot.video_director_plan)
    clip=plan['clip_plan'][1]
    clip.update(capability='TEMPORAL_EXTEND',continuity_to_previous='CONTINUOUS',requires_temporal_control=True,visual_state_indexes=[3],carry_in_state_index=2,
                selected_temporal_target_ids=['KF3'],temporal_anchor_ids=['clip-2-KF3'])
    plan['keyframes']=[{'index':2,'time_seconds':8,'description':'carry'}, {'index':3,'time_seconds':15,'description':'target','image_url':'/kf3.png'}]
    plan['temporal_anchors']=[{'anchor_id':'clip-2-KF3','time_seconds':7,'image_url':'/kf3.png','source':{'id':'KF3','keyframe_index':3}}]
    projection=project_effective_execution(plan,clip,'EXTEND_ONLY')
    metadata=json.loads(task.metadata_json)
    metadata.update(continuation_mode='EXTEND_ONLY',execution_projection=projection_record(projection),planned_capability='TEMPORAL_EXTEND',effective_capability='EXTEND')
    shot.video_director_plan=json.dumps(plan)
    task.metadata_json=json.dumps(metadata);db.commit();options['clip_metadata']=metadata
    return metadata


@pytest.mark.asyncio
@pytest.mark.parametrize('route',['phase_b','legacy'])
@pytest.mark.parametrize('action',['retry','restart','cancel'])
async def test_policy_survives_real_persist_retry_restore_and_cancel(setup_retry,db_session,db_engine,monkeypatch,route,action):
    manager,create=setup_retry
    task,shot,previous,artifact,args,options=create('EXTEND',route)
    frozen=freeze_policy(db_session,task,shot,options)
    calls=install_handler(monkeypatch,db_engine)
    try:
        video.enqueue_shot_video_task(*args,**options);await drained(manager);db_session.expire_all()
        original=db_session.query(BackgroundJob).one();original_state=(original.status,original.payload_json,original.attempts)
        if action=='restart':monkeypatch.setattr(manager.worker('shot_video'),'signal',lambda _:None)
        result=TaskService(db_session).retry_task(task.id)
        assert result['success'],result
        assert not TaskService(db_session).retry_task(task.id)['success']
        if action=='cancel':
            assert (await TaskService(db_session).cancel_task(task.id))['success']
        elif action=='restart':
            restarted=WorkerManager(sessionmaker(bind=db_engine))
            try:
                assert restarted.resume_persisted()==1
                await drained(restarted)
                assert restarted.resume_persisted()==0
            finally:await restarted.stop()
        await drained(manager);db_session.expire_all()
        assert len(calls)==(1 if action=='cancel' else 2)
        assert task.status==('cancelled' if action=='cancel' else 'completed')
        assert (original.status,original.payload_json,original.attempts)==original_state
        assert db_session.query(BackgroundJob).count()==2
        for job in db_session.query(BackgroundJob):
            payload=json.loads(job.payload_json)['clip_metadata']
            assert payload['continuation_mode']=='EXTEND_ONLY'
            assert payload['execution_projection']==frozen['execution_projection']
            assert payload['capability']=='EXTEND' and payload['h3_prompt_pipeline']==route
        assert json.loads(shot.video_director_plan)['clip_plan'][1]['capability']=='TEMPORAL_EXTEND'
    finally:await manager.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('damage',['receipt','previous','policy'])
async def test_unsafe_retry_still_stops_before_queue(setup_retry,db_session,db_engine,monkeypatch,damage):
    manager,create=setup_retry;task,shot,previous,artifact,args,options=create('EXTEND')
    freeze_policy(db_session,task,shot,options);calls=install_handler(monkeypatch,db_engine)
    try:
        video.enqueue_shot_video_task(*args,**options);await drained(manager);db_session.expire_all()
        if damage=='receipt':task.status='failed';task.result_url=None
        elif damage=='previous':artifact.unlink()
        else:
            metadata=json.loads(task.metadata_json);metadata['continuation_mode']='AUTO';task.metadata_json=json.dumps(metadata)
        db_session.commit()
        assert not TaskService(db_session).retry_task(task.id)['success']
        await drained(manager)
        assert len(calls)==1 and db_session.query(BackgroundJob).count()==1
    finally:await manager.stop()


@pytest.mark.asyncio
async def test_batch_continues_in_original_order_using_frozen_policy(db_session,monkeypatch,tmp_path):
    from app.api import shots as api
    from test_semantic_batch_scheduler import _fixture,_install_execution_fake
    _,_,shot,parent,child=_fixture(db_session)
    plan=json.loads(shot.video_director_plan)
    plan['keyframes']=[{'index':2,'description':'target','time_seconds':8,'image_url':'/kf2.png'}]
    plan['clip_plan'][1].update(visual_state_indexes=[2],requires_temporal_control=True,
        selected_temporal_target_ids=['KF2'],temporal_anchor_ids=['clip-2-KF2'])
    plan['temporal_anchors']=[{'anchor_id':'clip-2-KF2','source':{'id':'KF2','keyframe_index':2},'image_url':'/kf2.png'}]
    shot.video_director_plan=json.dumps(plan)
    metadata=json.loads(child.metadata_json);metadata.update(continuation_mode='EXTEND_ONLY',h3_prompt_pipeline='phase_b');child.metadata_json=json.dumps(metadata);db_session.commit()
    calls=[];_install_execution_fake(db_session,monkeypatch,tmp_path,calls)
    fake=api.execute_semantic_clip;projections=[]
    async def capture(*args,**kwargs):
        request=args[4];assert request.continuation_mode=='EXTEND_ONLY'
        original=json.loads(shot.video_director_plan)['clip_plan'][args[3]-1]
        projections.append(project_effective_execution(json.loads(shot.video_director_plan),original,request.continuation_mode))
        return await fake(*args,**kwargs)
    monkeypatch.setattr(api,'execute_semantic_clip',capture)
    assert await api._run_semantic_shot_for_batch(db_session,parent,child,shot)=='completed'
    assert calls==[1,2,3]
    assert [p['planned_capability'] for p in projections]==['GENERATE','TEMPORAL_EXTEND','EXTEND']
    assert [p['effective_capability'] for p in projections]==['GENERATE','EXTEND','EXTEND']


@pytest.mark.parametrize('entry',['batch','auto'])
@pytest.mark.parametrize('mode',['AUTO','EXTEND_ONLY'])
def test_creation_freezes_policy_on_parent_and_children(client,db_session,monkeypatch,entry,mode):
    from app.api import shots as api
    from test_semantic_batch_scheduler import _fixture
    novel,chapter,shot,parent,child=_fixture(db_session,capabilities=('GENERATE',))
    db_session.delete(parent);db_session.delete(child);db_session.commit()
    monkeypatch.setattr(api,'enqueue_shot_video_batch_task',lambda _:None)
    url=f'/api/novels/{novel.id}/chapters/{chapter.id}/'
    body={'continuation_mode':mode}
    if entry=='batch':url+='shot-videos/batch';body['shot_ids']=[shot.id]
    else:url+=f'shots/{shot.id}/auto-generation/start'
    r=client.post(url,json=body)
    assert r.status_code==200,r.text
    tasks=db_session.query(Task).all()
    assert len(tasks)==2 and all(json.loads(t.metadata_json)['continuation_mode']==mode for t in tasks)


def test_policy_requests_reject_unknown_modes():
    from pydantic import ValidationError
    from app.api.shots import BatchShotVideoRequest,SemanticClipGenerateRequest,PrepareRequiredImagesRequest,AutoGenerationRequest
    from app.schemas.shot import GenerateVideoDirectorClipRequest
    for cls,required in [(BatchShotVideoRequest,{'shot_ids':['s']}),(SemanticClipGenerateRequest,{}),
                         (PrepareRequiredImagesRequest,{'clip_plan_revision':1}),(AutoGenerationRequest,{}),(GenerateVideoDirectorClipRequest,{})]:
        assert cls(**required).continuation_mode=='AUTO'
        with pytest.raises(ValidationError):cls(**required,continuation_mode='LEGACY')


@pytest.mark.asyncio
async def test_assembly_accepts_frozen_effective_mode_and_preserves_planned_mode(db_session,persistence,monkeypatch):
    from test_continuous_clip_native_av import persist_native
    from app.services.shot_video_service import validate_semantic_clip_artifact,_continuous_assembly_projection
    novel,chapter,shot,_=persistence
    task,_=await persist_native(db_session,persistence,'EXTEND')
    plan=json.loads(shot.video_director_plan);clip=plan['clip_plan'][1]
    clip.update(capability='TEMPORAL_EXTEND',continuity_to_previous='CONTINUOUS',requires_temporal_control=True,visual_state_indexes=[3],carry_in_state_index=2,
                selected_temporal_target_ids=['KF3'],temporal_anchor_ids=['clip-2-KF3'])
    plan['keyframes']=[{'index':2,'description':'carry'}, {'index':3,'description':'target','image_url':'/kf3.png'}]
    plan['temporal_anchors']=[{'anchor_id':'clip-2-KF3','image_url':'/kf3.png','source':{'id':'KF3','keyframe_index':3}}]
    projection=project_effective_execution(plan,clip,'EXTEND_ONLY')
    metadata=json.loads(task.metadata_json);metadata.update(continuation_mode='EXTEND_ONLY',execution_projection=projection_record(projection))
    task.metadata_json=json.dumps(metadata);shot.video_director_plan=json.dumps(plan);db_session.commit()
    validated=validate_semantic_clip_artifact(db_session,shot,clip,1,novel.id,chapter.id)
    assert validated[0].id==task.id
    first=plan['clip_plan'][0]
    first_validated=validate_semantic_clip_artifact(db_session,shot,first,1,novel.id,chapter.id)
    output=_continuous_assembly_projection(db_session,shot,[(first,*first_validated),(clip,*validated)],novel.id,chapter.id)
    assert output # Real provenance and native AV checks ran; no media generation.
    from app.services import required_visual_state_images as images
    monkeypatch.setattr(images,'url_to_local_path',video.url_to_local_path)
    assert images._has_approved_previous_av(db_session,chapter,shot,plan,{'previous_clip_index':2})
    assert json.loads(shot.video_director_plan)['clip_plan'][1]['capability']=='TEMPORAL_EXTEND'


@pytest.mark.parametrize('mode',[None,'AUTO','EXTEND_ONLY'])
def test_task_summary_preserves_frozen_policy_like_detail(client,db_session,mode):
    """The real list endpoint used by Clip cards must retain the frozen policy."""
    metadata={'execution_scope':'CLIP','clip_index':6,'clip_plan_revision':1,'capability':'TEMPORAL_EXTEND'}
    policy_fields=['continuation_mode','planned_capability','effective_capability','execution_projection','suppressed_temporal_anchor_ids']
    if mode is not None:
        effective='EXTEND' if mode=='EXTEND_ONLY' else 'TEMPORAL_EXTEND'
        suppressed=['clip-6-KF8'] if mode=='EXTEND_ONLY' else []
        metadata.update(continuation_mode=mode,planned_capability='TEMPORAL_EXTEND',effective_capability=effective,
                        capability=effective,suppressed_temporal_anchor_ids=suppressed,
                        execution_projection={'continuation_mode':mode,'planned_capability':'TEMPORAL_EXTEND',
                        'effective_capability':effective,'suppressed_temporal_anchor_ids':suppressed,'planned_clip':{'clip_index':6}})
    stored=json.dumps(metadata)
    task=Task(type='shot_video',name='offline frozen summary',status='completed',metadata_json=stored)
    db_session.add(task);db_session.commit()
    detail=client.get(f'/api/tasks/{task.id}').json()['data']['clipExecution']
    summary_response=client.get('/api/tasks/?summary=true&type=shot_video')
    assert summary_response.status_code==200
    summary=next(t for t in summary_response.json()['data'] if t['id']==task.id)['clipExecution']
    for key in policy_fields:
        if mode is None:assert key not in summary and key not in detail
        else:assert summary.get(key)==detail[key]==metadata[key],key
    db_session.refresh(task);assert task.metadata_json==stored
