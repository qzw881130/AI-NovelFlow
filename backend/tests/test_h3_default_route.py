"""Default changes affect new requests only; external generation is forbidden."""
import json
from copy import deepcopy

import pytest
from sqlalchemy.orm import sessionmaker

from app.constants.h3_prompt_pipeline import DEFAULT_H3_PROMPT_PIPELINE, persisted_h3_prompt_pipeline
from app.models.background_job import BackgroundJob
from app.models.task import Task
from app.services import shot_video_service as video
from app.services.background_workers import WorkerManager
from app.services.task_service import TaskService
from test_persistent_shot_video_retry import setup_retry, install_handler, drained


@pytest.mark.parametrize('metadata,expected', [({}, 'legacy'), ({'h3_prompt_pipeline': 'legacy'}, 'legacy'),
    ({'h3_prompt_pipeline': 'phase_b'}, 'phase_b')])
def test_persisted_route_is_independent_of_new_request_default(metadata, expected):
    assert DEFAULT_H3_PROMPT_PIPELINE == 'phase_b'
    original = deepcopy(metadata)
    assert persisted_h3_prompt_pipeline(metadata) == expected
    assert metadata == original


@pytest.mark.parametrize('metadata', [{'h3_prompt_pipeline': 'automatic'}, {'h3_prompt_pipeline': ''},
    {'h3_prompt_pipeline': None}, {'h3_phase_b': {'version': 'H3_PHASE_B_LIMITED_V2'}}])
def test_unknown_or_ambiguous_saved_route_is_not_silently_legacy(metadata):
    with pytest.raises(ValueError, match='H3_PROMPT_PIPELINE_'):
        persisted_h3_prompt_pipeline(metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize('stored_route', [None, 'legacy', 'phase_b'])
async def test_persist_restart_and_explicit_retry_preserve_historical_route(
    setup_retry, db_session, db_engine, monkeypatch, stored_route,
):
    manager, create = setup_retry
    task, _, _, _, args, options = create(route=stored_route or 'legacy')
    if stored_route is None:
        meta=json.loads(task.metadata_json);meta.pop('h3_prompt_pipeline')
        task.metadata_json=json.dumps(meta);options['clip_metadata']=meta;db_session.commit()
    calls=install_handler(monkeypatch,db_engine)
    # Persist a descriptor without running it, then recover with a real fresh manager.
    monkeypatch.setattr(manager.worker('shot_video'),'signal',lambda _:None)
    video.enqueue_shot_video_task(*args,**options)
    job=db_session.query(BackgroundJob).one();original_payload=job.payload_json
    restarted=WorkerManager(sessionmaker(bind=db_engine))
    try:
        assert restarted.resume_persisted()==1
        await drained(restarted);db_session.expire_all()
        assert task.status=='completed' and len(calls)==1
        expected=stored_route or 'legacy'
        assert persisted_h3_prompt_pipeline(calls[0][1]['clip_metadata'])==expected
        assert TaskService(db_session).retry_task(task.id)['success']
        db_session.expire_all()
        assert restarted.resume_persisted()==1
        await drained(restarted);db_session.expire_all()
        assert len(calls)==2 and task.status=='completed'
        assert persisted_h3_prompt_pipeline(calls[1][1]['clip_metadata'])==expected
        assert calls[1][1]['clip_metadata'].get('h3_prompt_pipeline')==stored_route
        assert json.loads(task.metadata_json).get('h3_prompt_pipeline')==stored_route
        assert job.payload_json==original_payload and job.status=='completed'
        assert restarted.resume_persisted()==0
    finally:
        await restarted.stop();await manager.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('metadata,payload,error', [
    ({'h3_prompt_pipeline':'unknown'}, None, 'H3_PROMPT_PIPELINE_INVALID'),
    ({'h3_prompt_pipeline':'phase_b'}, {'h3_prompt_pipeline':'legacy'}, 'H3_PROMPT_PIPELINE_MISMATCH'),
    ({'h3_phase_b':{'version':'H3_PHASE_B_LIMITED_V2'}}, None, 'H3_PROMPT_PIPELINE_MISSING'),
])
async def test_actual_worker_rejects_invalid_route_before_external_work(db_session, monkeypatch, metadata,payload,error):
    from app.services.llm_service import LLMService
    from app.services.comfyui.client import ComfyUIClient
    async def forbidden(*a,**kw): pytest.fail('route rejection must not generate')
    monkeypatch.setattr(LLMService,'chat_completion',forbidden)
    monkeypatch.setattr(ComfyUIClient,'queue_prompt',forbidden)
    monkeypatch.setattr(video,'SessionLocal',lambda:db_session)
    monkeypatch.setattr(db_session,'close',lambda:None)
    task=Task(id='invalid-route',name='invalid',type='shot_video',status='pending',metadata_json=json.dumps(metadata))
    db_session.add(task);db_session.commit()
    await video.generate_shot_video_task(task.id,'n','c',1,'workflow','image',clip_metadata=payload)
    assert task.status=='failed' and error in task.error_message
    assert json.loads(task.metadata_json)==metadata
    if error != 'H3_PROMPT_PIPELINE_MISMATCH':
        retry = TaskService(db_session).retry_task(task.id)
        assert not retry['success'] and retry['status_code'] == 409
        assert error in retry['message']


@pytest.mark.asyncio
@pytest.mark.parametrize('route', [None,'legacy','phase_b'])
async def test_historical_batch_children_use_saved_route(db_session, monkeypatch,tmp_path,route):
    from test_semantic_batch_scheduler import _fixture,_install_execution_fake
    from app.api import shots as api
    _,_,shot,parent,child=_fixture(db_session)
    if route is not None:
        meta=json.loads(child.metadata_json);meta['h3_prompt_pipeline']=route;child.metadata_json=json.dumps(meta);db_session.commit()
    calls=[];_install_execution_fake(db_session,monkeypatch,tmp_path,calls)
    execute=api.execute_semantic_clip
    async def checked(*a,**kw):
        assert a[4].h3_prompt_pipeline==(route or 'legacy')
        return await execute(*a,**kw)
    monkeypatch.setattr(api,'execute_semantic_clip',checked)
    assert await api._run_semantic_shot_for_batch(db_session,parent,child,shot)=='completed'
    assert calls==[1,2,3]


@pytest.mark.parametrize('path,body', [
    ('/api/novels/n/chapters/c/shot-videos/batch', {'shot_ids':['s']}),
    ('/api/novels/n/chapters/c/shots/s/video-director/clips/1/generate', {'clip_plan_revision':1}),
])
def test_unknown_route_is_http_422_without_task_creation(client,db_session,path,body):
    response=client.post(path,json={**body,'h3_prompt_pipeline':'automatic'})
    assert response.status_code==422
    assert response.json()['detail'][0]['loc'][-1]=='h3_prompt_pipeline'
    assert db_session.query(Task).count()==0
