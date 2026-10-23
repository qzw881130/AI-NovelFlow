"""Candidate isolation using saved test3 C6, real durable worker and fake external I/O.

No production writes or generated media: fake bytes are downloaded only to tmp_path.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.novel import Novel, Chapter, Character, Prop
from app.models.shot import Shot
from app.models.prompt_template import PromptTemplate
from app.models.background_job import BackgroundJob
from app.repositories import NovelRepository, ChapterRepository, ShotRepository, TaskRepository
from app.api import shots as api
from app.services import shot_video_service as worker, background_workers, h3_phase_b_pipeline as pipe
from app.services import continuous_clip_av as av
from app.services.background_workers import WorkerManager
from app.services.task_service import TaskService
from app.services.video_result_mode import is_candidate, result_mode, freeze_candidate_source, validate_candidate_source
from app.services.comfyui.service import ComfyUIService
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.llm_service import LLMService
from test_effective_execution_policy import saved_c6
from test_h3_phase_b_pipeline import FakeComfy, FakeDirector, offline_only, saved, NAMES
from test_persistent_shot_video_retry import drained, setup_retry, install_handler
from test_continuous_clip_native_av import physical, persistence, persist_native


@pytest.fixture
def saved_environment(db_session, db_engine, monkeypatch, tmp_path):
    data=saved_c6(); plan=deepcopy(data['plan'])
    novel=Novel(title='Offline test3');db_session.add(novel);db_session.flush()
    chapter=Chapter(novel_id=novel.id,title='Offline test3',number=1);db_session.add(chapter);db_session.flush()
    shot=Shot(**{k:v for k,v in data['shot'].items() if k not in {'id','chapter_id'}},chapter_id=chapter.id,
        video_director_plan=json.dumps(plan,ensure_ascii=False),video_url=plan['merged_video_url'],video_status='completed')
    db_session.add(shot);db_session.flush()
    db_session.add_all([Character(novel_id=novel.id,name=n,appearance=a) for n,a in data['character_appearances'].items()])
    db_session.add_all([Prop(novel_id=novel.id,**p) for p in data['props']])
    from app.services.h3_single_stage_experiment import PHASE_B_TEMPLATE
    db_session.add(PromptTemplate(name='Offline Phase B',type=pipe.TEMPLATE_TYPE,is_active=True,is_system=True,template=PHASE_B_TEMPLATE.read_text()))
    temporal=saved(NAMES[2]); temporal_wf=deepcopy(temporal['workflow'])
    temporal_wf['workflow_json']=Path(temporal['physical_evidence']['reference_binder']['template_path']).read_text()
    for wf in [data['workflow'],temporal_wf]:
        db_session.add(Workflow(**{**{k:v for k,v in wf.items() if k in ['id','name','type','workflow_json','node_mapping','extension']}, 'name':wf.get('name') or 'Offline frozen workflow'},is_active=True))
    previous=data['previous_clip'];c5=plan['clip_plan'][4]
    previous_meta={'execution_scope':'CLIP','clip_index':5,'clip_plan_revision':1,'approval_status':'APPROVED',
        'physical_output':c5['physical_output'],'execution_contract':{'capability':c5['capability'],'artifact_kind':av.NATIVE_CONTINUITY_OUTPUT,'previous_clip':c5['physical_output']['previous']}}
    old=Task(id=previous['generated_by_task_id'],name='Original C5',type='shot_video',status='completed',
        novel_id=novel.id,chapter_id=chapter.id,shot_id=shot.id,result_url=previous['result_url'],metadata_json=json.dumps(previous_meta))
    db_session.add(old);db_session.commit()
    resources={'references':deepcopy(data['manifest']['references']),'skipped_references':[]}
    monkeypatch.setattr(api,'resolve_clip_reference_resources',lambda *a,**k:deepcopy(resources))
    monkeypatch.setattr(worker,'resolve_clip_reference_resources',lambda *a,**k:deepcopy(resources))
    manager=WorkerManager(sessionmaker(bind=db_engine,autoflush=False))
    monkeypatch.setattr(background_workers,'worker_manager',manager)
    monkeypatch.setattr(worker,'worker_manager',manager)
    monkeypatch.setattr(worker,'_queued_shot_video_task_ids',set())
    monkeypatch.setattr(worker,'SessionLocal',sessionmaker(bind=db_engine,autoflush=False))
    client=FakeComfy();service=object.__new__(ComfyUIService);service.builder=WorkflowBuilder();service.client=client
    monkeypatch.setattr(worker,'ComfyUIService',lambda:service)
    # Keep strict Previous AV resolver. Physical probing reads saved evidence for
    # existing C5; generated output probing is fake and never creates real media.
    real_probe=av.probe_clip_av
    def probe(path):
        if Path(path).parent==tmp_path:return physical(previous['physical_output']['frame_count']+300,Path(path).read_bytes())
        if str(path).endswith(c5['local_path'].split('/')[-1]):return deepcopy(previous['physical_output'])
        return real_probe(path)
    monkeypatch.setattr(av,'probe_clip_av',probe)
    monkeypatch.setattr(worker,'probe_clip_av',probe)
    monkeypatch.setattr(worker,'_probe_video_duration',lambda p:probe(p)['video_duration'])
    monkeypatch.setattr(worker.file_storage,'base_dir',tmp_path)
    downloads=[]
    async def download(**kwargs):
        path=tmp_path/(kwargs['filename_suffix']+f'_{len(downloads)}.mp4')
        path.write_bytes(b'fake candidate AV');downloads.append(path);return str(path)
    monkeypatch.setattr(worker.file_storage,'download_video',download)
    async def preserve(*args):return {'policy':'OFFLINE_FAKE_AV'}
    monkeypatch.setattr(worker,'preserve_native_av',preserve)
    # Any accidental invalidation is an immediate test failure for candidates.
    original_invalidate=worker.invalidate_current_canonical_execution
    invalidations=[]
    def invalidate(*a,**kw):invalidations.append(a[1]);return original_invalidate(*a,**kw)
    monkeypatch.setattr(worker,'invalidate_current_canonical_execution',invalidate)
    def snapshot():
        db_session.expire_all()
        return {'shot':{c.name:deepcopy(getattr(shot,c.name)) for c in Shot.__table__.columns},
                'c5':{c.name:deepcopy(getattr(old,c.name)) for c in Task.__table__.columns}}
    return dict(data=data,plan=plan,novel=novel,shot=shot,previous=old,manager=manager,client=client,
                snapshot=snapshot,downloads=downloads,invalidations=invalidations)


def install_director(monkeypatch,env,policy,fail=False):
    decisions=deepcopy(env['data']['original_decisions'])
    if policy=='EXTEND_ONLY':decisions['anchors']=[a for a in decisions['anchors'] if not a['id'].startswith('clip-')]
    decisions['detailed_description']='<Subject 1>按 Canonical 范围完成动作。[[SPEECH_1]][[SPEECH_2]]'
    decisions['overall_soundscape']='<Subject 1>的衣料声及场景环境声。'
    if fail:decisions['detailed_description']='[[SPEECH_999]]'
    llm=FakeDirector(decisions)
    async def reply(self, **kw):
        from h3_language_fakes import language_response
        llm.content = language_response(json.loads(kw['user_content']), decisions)
        if fail:
            llm.content['detailed_description'] = '[[SPEECH_999]]'
        return await llm.chat_completion(**kw)
    monkeypatch.setattr(LLMService,'chat_completion',reply)
    return llm


async def create(db,env,policy='EXTEND_ONLY',mode='CANDIDATE_ONLY'):
    return await api.execute_semantic_clip(env['novel'].id,env['shot'].chapter_id,env['shot'].id,6,
        api.SemanticClipGenerateRequest(clip_plan_revision=1,continuation_mode=policy,result_mode=mode),db,
        NovelRepository(db),ChapterRepository(db),TaskRepository(db),ShotRepository(db))


@pytest.mark.asyncio
@pytest.mark.parametrize('policy',['AUTO','EXTEND_ONLY'])
@pytest.mark.parametrize('outcome',['success','director_failure','comfy_failure','cancel_upload','restore'])
async def test_saved_c6_real_persist_worker_and_save_isolation(saved_environment,db_session,db_engine,monkeypatch,policy,outcome):
    e=saved_environment;m=e['manager'];before=e['snapshot']();llm=install_director(monkeypatch,e,policy,outcome=='director_failure')
    if outcome=='restore':monkeypatch.setattr(m.worker('shot_video'),'signal',lambda _:None)
    if outcome=='comfy_failure':
        async def failure(*a,**k):return {'success':False,'message':'offline temporary Comfy error'}
        e['client'].wait_for_result=failure
    try:
        response=await create(db_session,e,policy);task=db_session.get(Task,response['data']['taskId'])
        frozen=json.loads(task.metadata_json)
        assert frozen['result_mode']=='CANDIDATE_ONLY'
        assert frozen['candidate_source']['clip_plan']==e['plan']
        assert frozen['candidate_execution_inputs']['execution_contract']['previous_clip']['generated_by_task_id']==e['previous'].id
        assert e['snapshot']()==before
        if outcome=='cancel_upload':
            upload=e['client'].upload_image
            async def cancel(path):
                task.status='cancelled';db_session.commit();return await upload(path)
            e['client'].upload_image=cancel
        if outcome=='restore':
            restarted=WorkerManager(sessionmaker(bind=db_engine,autoflush=False))
            try:
                assert restarted.resume_persisted()==1
                await drained(restarted)
            finally:await restarted.stop()
        else:await drained(m)
        db_session.expire_all()
        assert e['snapshot']()==before
        assert not e['invalidations']
        assert db_session.query(BackgroundJob).count()==1
        payload=json.loads(db_session.query(BackgroundJob).one().payload_json)['clip_metadata']
        assert payload['result_mode']=='CANDIDATE_ONLY' and payload['continuation_mode']==policy
        if outcome in {'success','restore'}:
            assert task.status=='completed',task.error_message
            meta=json.loads(task.metadata_json);result=meta['candidate_result']
            assert len(llm.calls)==1 and len(e['client'].posts)==1
            assert result['sha256']==hashlib.sha256(Path(result['local_path']).read_bytes()).hexdigest()
            assert 'candidate_clip_6_'+task.id in result['local_path']
            assert task.result_url!=e['plan']['clip_plan'][5]['video_url']
            assert meta['approval_status']=='CANDIDATE' and result['adopted'] is False
            assert task.prompt_text and task.seed is not None and task.workflow_json and task.comfyui_prompt_id
            assert meta['h3_phase_b']['preflight']['passed'] and meta['h3_phase_b']['submission_preflight']['passed']
            assert meta['video_reference_manifest']['references']
            anchors=meta['execution_contract']['temporal_anchor_manifest']['anchors']
            assert len(anchors)==(0 if policy=='EXTEND_ONLY' else 1)
            assert all(r.get('source_keyframe_index')!=8 for r in meta['video_reference_manifest']['references'])
            from app.api.tasks import _task_summary_query,_format_task_summaries
            summary=_format_task_summaries(_task_summary_query(db_session,status_only=False).filter(Task.id==task.id).all(),status_only=False)[0]
            assert summary['clipExecution']['candidate_result']==result
            poll=_format_task_summaries(_task_summary_query(db_session,status_only=True).filter(Task.id==task.id).all(),status_only=True)[0]
            assert poll['resultMode']=='CANDIDATE_ONLY' and 'clipExecution' not in poll
            assert TaskService.format_task_list([task],{},{},{})[0]['clipExecution']['candidate_result']==result
            assert task.id not in [t.id for t in api._semantic_clip_tasks(db_session,e['shot'],1)]
        else:
            assert task.status==('cancelled' if outcome=='cancel_upload' else 'failed'),task.error_message
            assert not e['downloads']
            assert len(e['client'].posts)==(1 if outcome=='comfy_failure' else 0)
    finally:await m.stop()


@pytest.mark.asyncio
async def test_apply_still_adopts_and_invalidates_saved_c6(saved_environment,db_session,monkeypatch):
    e=saved_environment;before=e['snapshot']();install_director(monkeypatch,e,'EXTEND_ONLY')
    try:
        response=await create(db_session,e,mode='APPLY');await drained(e['manager']);db_session.expire_all()
        task=db_session.get(Task,response['data']['taskId']);assert task.status=='completed',task.error_message
        plan=json.loads(e['shot'].video_director_plan)
        assert plan['clip_plan'][5]['generated_by_task_id']==task.id
        assert plan['clip_plan'][5]['prompt_text']==task.prompt_text
        assert plan.get('merged_video_url') is None
        assert e['invalidations']==[{6}]
        assert e['snapshot']()['c5']==before['c5']
    finally:await e['manager'].stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('action',['retry','restart','cancel'])
async def test_candidate_freeze_survives_retry_and_restore(setup_retry,db_session,db_engine,monkeypatch,action):
    manager,create_task=setup_retry
    task,shot,previous,artifact,args,options=create_task('EXTEND')
    metadata=json.loads(task.metadata_json);metadata.update(result_mode='CANDIDATE_ONLY',continuation_mode='AUTO')
    metadata.update(freeze_candidate_source(shot,json.loads(shot.video_director_plan),{}))
    task.metadata_json=json.dumps(metadata);db_session.commit();options['clip_metadata']=metadata
    before=shot.video_director_plan;calls=install_handler(monkeypatch,db_engine)
    try:
        worker.enqueue_shot_video_task(*args,**options);await drained(manager)
        if action in {'restart','cancel'}:monkeypatch.setattr(manager.worker('shot_video'),'signal',lambda _:None)
        assert TaskService(db_session).retry_task(task.id)['success']
        assert not TaskService(db_session).retry_task(task.id)['success']
        if action=='cancel':await TaskService(db_session).cancel_task(task.id)
        elif action=='restart':
            resumed=WorkerManager(sessionmaker(bind=db_engine))
            try:assert resumed.resume_persisted()==1;await drained(resumed)
            finally:await resumed.stop()
        await drained(manager);db_session.expire_all()
        assert len(calls)==(1 if action=='cancel' else 2)
        for job in db_session.query(BackgroundJob):
            frozen=json.loads(job.payload_json)['clip_metadata']
            assert frozen['result_mode']=='CANDIDATE_ONLY' and frozen['candidate_source']==metadata['candidate_source']
        assert shot.video_director_plan==before
    finally:await manager.stop()


def test_defaults_and_unknown_result_modes():
    from pydantic import ValidationError
    from app.schemas.shot import GenerateVideoDirectorClipRequest
    for schema in [GenerateVideoDirectorClipRequest,api.SemanticClipGenerateRequest]:
        assert schema().result_mode=='APPLY'
        with pytest.raises(ValidationError):schema(result_mode='unknown')
    assert result_mode({})=='APPLY' and not is_candidate({})
    with pytest.raises(ValueError,match='RESULT_MODE_INVALID'):result_mode({'result_mode':'unknown'})


@pytest.mark.asyncio
async def test_candidate_cannot_be_previous_or_assembly_even_if_bound(db_session,persistence):
    task,contract=await persist_native(db_session,persistence,'EXTEND')
    novel,chapter,shot,_=persistence;plan=json.loads(shot.video_director_plan)
    meta=json.loads(task.metadata_json);meta['result_mode']='CANDIDATE_ONLY';task.metadata_json=json.dumps(meta);db_session.commit()
    source={'clip_index':2,'clip_plan_revision':1,'generated_by_task_id':task.id,'result_url':task.result_url}
    with pytest.raises(ValueError,match='PREVIOUS_AV_UNAVAILABLE'):
        worker.resolve_extend_previous_av(db_session,novel.id,chapter.id,shot,{'previous_clip_index':2,'clip_plan_revision':1},source)
    with pytest.raises(ValueError):worker.validate_semantic_clip_artifact(db_session,shot,plan['clip_plan'][1],1,novel.id,chapter.id)

@pytest.mark.asyncio
@pytest.mark.parametrize('damage',['source','resource','payload','download_failure','cancel_download'])
async def test_candidate_rejects_drift_and_save_interruptions_without_official_writes(saved_environment,db_session,monkeypatch,damage):
    e=saved_environment;m=e['manager'];install_director(monkeypatch,e,'EXTEND_ONLY')
    monkeypatch.setattr(m.worker('shot_video'),'signal',lambda _:None)
    try:
        response=await create(db_session,e);task=db_session.get(Task,response['data']['taskId'])
        job=db_session.query(BackgroundJob).one()
        if damage=='source':
            plan=json.loads(e['shot'].video_director_plan);plan['keyframes'][-1]['description']='concurrent change in isolated fixture'
            e['shot'].video_director_plan=json.dumps(plan);db_session.commit()
        if damage=='resource':
            frozen=json.loads(task.metadata_json);frozen['candidate_execution_inputs']['video_reference_manifest']['references'].reverse()
            task.metadata_json=json.dumps(frozen);db_session.commit()
        if damage=='payload':
            payload=json.loads(job.payload_json);payload['clip_metadata']['result_mode']='APPLY';job.payload_json=json.dumps(payload);db_session.commit()
            m._local_factories.clear()
        if damage in {'download_failure','cancel_download'}:
            download=worker.file_storage.download_video
            async def interrupted(**kwargs):
                if damage=='download_failure':return None
                path=await download(**kwargs)
                task.status='cancelled';db_session.commit();return path
            monkeypatch.setattr(worker.file_storage,'download_video',interrupted)
        before=e['snapshot']()
        await m.run_persisted(job.id);db_session.expire_all()
        assert e['snapshot']()==before
        assert task.status==('cancelled' if damage=='cancel_download' else 'failed')
        assert not task.result_url and not e['invalidations']
        assert len(e['client'].posts)==(1 if damage.endswith('download') or damage=='download_failure' else 0)
        if damage in {'source','resource','payload'}:
            assert any(code in task.error_message for code in ['CANDIDATE_SOURCE_CHANGED','CANDIDATE_EXECUTION_INPUTS_CHANGED','RESULT_MODE_PAYLOAD_MISMATCH'])
        if damage=='cancel_download':assert all(not p.exists() for p in e['downloads'])
    finally:await m.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('policy',['AUTO','EXTEND_ONLY'])
async def test_receipt_recovery_saves_candidate_without_adoption_or_resubmission(saved_environment,db_session,monkeypatch,policy):
    from app.services.clip_result_recovery import recover_completed_clip, INTERRUPTED_CLIP_ERROR
    e=saved_environment;m=e['manager'];install_director(monkeypatch,e,policy)
    original=worker._save_generated_video
    async def interrupted(result,task,*args,**kwargs):
        task.status='failed';task.error_message=INTERRUPTED_CLIP_ERROR;args[3].commit()
    monkeypatch.setattr(worker,'_save_generated_video',interrupted)
    try:
        before=e['snapshot']();response=await create(db_session,e,policy);await drained(m);db_session.expire_all()
        task=db_session.get(Task,response['data']['taskId'])
        assert task.status=='failed' and task.comfyui_prompt_id
        assert not TaskService(db_session).retry_task(task.id)['success']
        assert e['snapshot']()==before
        monkeypatch.setattr(worker,'_save_generated_video',original)
        from types import SimpleNamespace
        graph=json.loads(task.workflow_json)
        comfy=SimpleNamespace(client=SimpleNamespace(_parse_outputs=lambda *a,**k:{'success':True,'video_url':'/offline/output.mp4'}))
        history={'prompt':[0,task.comfyui_prompt_id,graph],'outputs':{'65':{'videos':[{'filename':'offline.mp4'}]}}}
        assert await recover_completed_clip(task,history,db_session,comfy)
        assert task.status=='completed' and json.loads(task.metadata_json)['candidate_result']['adopted'] is False
        assert len(e['client'].posts)==1 and e['snapshot']()==before
    finally:await m.stop()


@pytest.mark.asyncio
async def test_generate_candidate_saver_keeps_prompt_status_and_assembly(db_session,persistence):
    novel,chapter,shot,_=persistence
    shot.video_url='/official-shot.mp4';plan=json.loads(shot.video_director_plan)
    plan.update(assembly_status='COMPLETED',merged_video_url=shot.video_url)
    plan['clip_plan'][1].update(capability='GENERATE',execution_status='APPROVED',prompt_text='official prompt',prompt_projection={'official':True},video_url='/old-c2.mp4',generated_by_task_id='official-c2')
    shot.video_director_plan=json.dumps(plan);db_session.commit();before=shot.video_director_plan
    metadata={'result_mode':'CANDIDATE_ONLY','execution_scope':'CLIP','clip_index':2,'clip_plan_revision':1,'capability':'GENERATE','execution_contract':{'capability':'GENERATE','artifact_kind':'CLIP_ONLY'}}
    metadata.update(freeze_candidate_source(shot,plan,{}))
    task=Task(type='shot_video',status='running',name='offline generate candidate',novel_id=novel.id,chapter_id=chapter.id,shot_id=shot.id,metadata_json=json.dumps(metadata),prompt_text='candidate prompt')
    db_session.add(task);db_session.commit()
    await worker._save_generated_video({'success':True,'video_url':'/offline.mp4'},task,novel.id,chapter.id,1,db_session,task.id,ShotRepository(db_session),clip_metadata=metadata)
    assert task.status=='completed'
    assert shot.video_director_plan==before and shot.video_url=='/official-shot.mp4'
    assert json.loads(task.metadata_json)['candidate_result']['sha256']


def test_candidate_scope_and_both_intents_are_explicit(saved_environment,db_session,monkeypatch):
    # Batch/auto use their existing APPLY default; no candidate policy is inherited.
    assert api.SemanticClipGenerateRequest().result_mode=='APPLY'
    e=saved_environment
    frozen=freeze_candidate_source(e['shot'],e['plan'],{})
    validate_candidate_source(e['shot'],{'result_mode':'CANDIDATE_ONLY',**frozen})
    with pytest.raises(ValueError,match='CANDIDATE_SOURCE_CHANGED'):
        validate_candidate_source(e['shot'],{'result_mode':'CANDIDATE_ONLY'})


def test_candidate_cache_is_task_local_and_apply_cannot_reuse_it(db_session):
    from test_h3_phase_b_pipeline import make_case
    snap,args,_=make_case(db_session,NAMES[0]);task=args['task'];shot=args['shot'];before=shot.video_director_plan
    meta=json.loads(task.metadata_json);meta['result_mode']='CANDIDATE_ONLY';task.metadata_json=json.dumps(meta);db_session.commit()
    llm=FakeDirector(saved(NAMES[0],'_mock_response'))
    first=asyncio.run(pipe.build_phase_b_prompt(**args,llm=llm))
    meta=json.loads(task.metadata_json);meta['skip_llm_when_prompt_exists']=True;task.metadata_json=json.dumps(meta);db_session.commit()
    assert asyncio.run(pipe.build_phase_b_prompt(**args,llm=llm))==first
    assert len(llm.calls)==1 and shot.video_director_plan==before
    meta=json.loads(task.metadata_json);meta['result_mode']='APPLY';task.metadata_json=json.dumps(meta);db_session.commit()
    with pytest.raises(ValueError,match='PHASE_B_REUSABLE_PLAN_MISSING'):
        asyncio.run(pipe.build_phase_b_prompt(**args,llm=llm))
    assert len(llm.calls)==1
