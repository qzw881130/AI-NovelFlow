"""Phase A-2: in-memory DB and mocked existing entry points; no real calls."""
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.services.required_visual_state_images import (
    project_required_execution_images, state_provenance, frame_provenance,
    commit_visual_state_image, prepare_required_images, project_clip_execution_readiness,
)
from app.services.canonical_execution_invalidation import CanonicalExecutionConflict
from app.services.shot_keyframe_service import ShotKeyframeService
from app.services.task_service import TaskService


@pytest.fixture
def fixture(db_session, tmp_path):
    main=tmp_path/'main.png'; main.write_bytes(b'image')
    states=[{'index':i,'role':'START' if i==1 else 'INTERMEDIATE','time_seconds':t,
             'description':f'state-{i}','timed_visual_target':i in {2,4,7}}
            for i,t in enumerate([0,7.8,21,28.8,41,47.6,52.5,68],1)]
    clips=[dict(clip_index=i,start_time=start,end_time=end,previous_clip_index=i-1 if i>1 else None,
                capability='GENERATE' if i==1 else 'TEMPORAL_EXTEND' if i in {3,5} else 'EXTEND',
                visual_state_indexes=owned,carry_in_state_index=carry,selected_temporal_target_ids=selected,
                execution_status='PLANNED',continuity_to_previous='CONTINUOUS' if i>1 else 'NONE')
           for i,start,end,owned,carry,selected in [(1,0,8.05,[1,2],None,[]),(2,8.05,19.4,[],2,[]),
             (3,19.4,33.95,[3,4],2,['KF4']),(4,33.95,47.75,[5,6],4,[]),(5,47.75,56,[7],6,['KF7']),(6,56,68,[8],7,[])]]
    p={'canonical_visual_plan':True,'clip_plan_revision':2,'keyframes':states,'clip_plan':clips,
       'clip_plan_validation':{'passed':True,'temporal_contract':'ELIGIBLE_THEN_SELECTED_V1','composition_contract':'EARLY_COMPOSITION_V2'},
       'temporal_anchors':[{'anchor_id':f'clip-{ci}-KF{si}','image_url':None,
         'source':{'type':'KEYFRAME','id':f'KF{si}','keyframe_index':si}} for ci,si in [(3,4),(5,7)]]}
    shot=Shot(id='shot',chapter_id='chapter',index=1,description='test',image_url=str(main),
      video_director_plan=json.dumps(p),keyframes=json.dumps([{'frame_index':i-2,'plan_keyframe_index':i,'description':f'state-{i}'} for i in range(2,9)]))
    db_session.add_all([Novel(id='novel',title='test'),Chapter(id='chapter',novel_id='novel',number=1,title='test'),shot]);db_session.commit()
    return shot


def plan(shot):return json.loads(shot.video_director_plan)
def save(db,shot,p):shot.video_director_plan=json.dumps(p);db.commit()
def task(db,shot,si,status='running',id=None,revision=None):
    provenance=state_provenance(shot,si)
    if revision is not None:provenance['clip_plan_revision']=revision
    row=Task(id=id or f'image-{si}-{status}',type='shot_image' if si==1 else 'keyframe_image',shot_id=shot.id,
      novel_id='novel',chapter_id='chapter',name=f'生成关键帧图片: {shot.id}-{si-2}',status=status,
      metadata_json=json.dumps({'canonical_image_provenance':provenance}),error_message='mock failure' if status=='failed' else None,
      current_step='mock step',created_at=datetime.utcnow())
    if revision is None:
        if si==1:shot.image_task_id=row.id
        else:
            frames=json.loads(shot.keyframes);frames[si-2]['image_task_id']=row.id;shot.keyframes=json.dumps(frames)
    db.add(row);db.commit();return row


def test_projection_two_authorities_is_derived(fixture):
    before=fixture.video_director_plan;items=project_required_execution_images(fixture,plan(fixture))
    assert [i['state_index'] for i in items]==[1,4,7]
    assert [i['kind'] for i in items]==['GENERATE_VISUAL_START','SELECTED_TEMPORAL_TARGET','SELECTED_TEMPORAL_TARGET']
    assert items[0]['ready'] and items[0]['image_source']=='SHOT_IMAGE'
    assert items[1]['shot_time']==28.8 and items[1]['clip_local_time']==9.4
    assert items[2]['consumer_clip_indexes']==[5] and fixture.video_director_plan==before
    assert not {2,3,5,6,8}.intersection(i['state_index'] for i in items)


def test_multiple_selected_and_dedupe(db_session,fixture):
    p=plan(fixture);p['clip_plan'][2]['selected_temporal_target_ids'].append('KF3')
    p['clip_plan'].append(dict(clip_index=7,capability='GENERATE',visual_state_indexes=[4],start_time=28.8));save(db_session,fixture,p)
    items=project_required_execution_images(fixture,p)
    assert [i['state_index'] for i in items]==[1,4,3,7]
    assert next(i for i in items if i['state_index']==4)['consumer_clip_indexes']==[3,7]


def test_generate_first_owned_not_all_owned(db_session,fixture):
    p=plan(fixture);p['clip_plan'][3].update(capability='GENERATE',visual_state_indexes=[5,6]);save(db_session,fixture,p)
    items=project_required_execution_images(fixture,p)
    assert next(i for i in items if i['state_index']==5)['kind']=='GENERATE_VISUAL_START'
    assert 6 not in [i['state_index'] for i in items]


@pytest.mark.asyncio
async def test_active_sibling_missing_only_and_zero_video(db_session,fixture):
    active=task(db_session,fixture,4);calls=[]
    async def submit(frame,provenance):
        calls.append((frame,provenance));return task(db_session,fixture,provenance['state_index'],'pending').id
    start=AsyncMock();items=await prepare_required_images(db_session,fixture,2,submit,start)
    assert [i['status'] for i in items]==['READY','REUSED','QUEUED'] and items[1]['task_id']==active.id
    assert [p['state_index'] for _,p in calls]==[7];start.assert_not_awaited()
    assert db_session.query(Task).filter(Task.type.like('%video%')).count()==0
    assert db_session.query(Task).filter(Task.parent_task_id.isnot(None)).count()==0


@pytest.mark.asyncio
async def test_clip_scope_retry_only_one(db_session,fixture):
    task(db_session,fixture,4,'failed');submit=AsyncMock(return_value='retry-4');start=AsyncMock()
    items=await prepare_required_images(db_session,fixture,2,submit,start,clip_indexes=[3],state_indexes=[4])
    assert len(items)==1 and items[0]['status']=='QUEUED'
    assert submit.await_args.args==(2,state_provenance(fixture,4));start.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_failure_continues(db_session,fixture):
    async def submit(frame,provenance):
        if provenance['state_index']==4:raise ValueError('KF4 failed')
        return 'new-KF7'
    items=await prepare_required_images(db_session,fixture,2,submit,AsyncMock())
    assert [i['status'] for i in items]==['READY','FAILED','QUEUED']
    assert items[1]['reason']=='KF4 failed' and items[2]['task_id']=='new-KF7'


@pytest.mark.asyncio
async def test_start_missing_existing_main_path(db_session,fixture):
    fixture.image_url=None;db_session.commit();submit=AsyncMock();start=AsyncMock(return_value='main-task')
    items=await prepare_required_images(db_session,fixture,2,submit,start,clip_indexes=[1])
    assert items[0]['status']=='QUEUED' and items[0]['state_id']=='KF1'
    assert start.await_args.args[0]==state_provenance(fixture,1);submit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('revision,clips,states',[(1,None,None),(2,[99],None),(2,[3],[2])])
async def test_reject_stale_revision_or_nonrequired_scope(db_session,fixture,revision,clips,states):
    submit=AsyncMock();start=AsyncMock()
    with pytest.raises((ValueError,CanonicalExecutionConflict)):
        await prepare_required_images(db_session,fixture,revision,submit,start,clip_indexes=clips,state_indexes=states)
    submit.assert_not_awaited();start.assert_not_awaited()


def test_history_failure_cannot_override_ready_or_replan(db_session,fixture,tmp_path):
    failed=task(db_session,fixture,4,'failed',revision=1)
    assert project_required_execution_images(fixture,plan(fixture),[failed])[1]['failure'] is None
    current=task(db_session,fixture,4,'failed',id='current');image=tmp_path/'ready.png';image.write_bytes(b'img')
    commit_visual_state_image(db_session,fixture,str(image),frame_index=2,expected_provenance=state_provenance(fixture,4));db_session.commit()
    item=project_required_execution_images(fixture,plan(fixture),[current])[1];assert item['ready'] and item['failure'] is None


@pytest.mark.parametrize('change',['revision','description','time','mapping','no-provenance'])
def test_stale_completion_no_binding(db_session,fixture,change):
    expected=frame_provenance(fixture,2);p=plan(fixture)
    if change=='revision':p['clip_plan_revision']=3
    if change=='description':p['keyframes'][3]['description']='replanned'
    if change=='time':p['keyframes'][3]['time_seconds']=29
    if change=='mapping':
        frames=json.loads(fixture.keyframes);frames[2]['plan_keyframe_index']=7;fixture.keyframes=json.dumps(frames)
    if change=='no-provenance':expected=None
    save(db_session,fixture,p);before=(fixture.video_director_plan,fixture.keyframes)
    with pytest.raises(CanonicalExecutionConflict):
        commit_visual_state_image(db_session,fixture,'/new.png',frame_index=2,expected_provenance=expected)
    assert (fixture.video_director_plan,fixture.keyframes)==before


def consumer(db,shot,ci,si,url,status='completed',ordinary=False):
    p=plan(shot);video=f'/video-{ci}.mp4';p['clip_plan'][ci-1].update(generated_by_task_id=f'video-{ci}',video_url=video,execution_status='APPROVED')
    metadata={'execution_scope':'CLIP','clip_plan_revision':2,'clip_index':ci,
      'video_reference_manifest':{'references':[{'source_keyframe_index':si,'image_url':url}] if ordinary else []},
      'execution_contract':{'artifact_kind':'CLIP_ONLY','temporal_anchor_manifest':{'anchors':[] if ordinary else [{'image_url':url,'source':{'id':f'KF{si}','keyframe_index':si}}]}}}
    db.add(Task(id=f'video-{ci}',name=f'video-{ci}',type='shot_video',shot_id=shot.id,status=status,result_url=video,metadata_json=json.dumps(metadata)));save(db,shot,p)


@pytest.mark.parametrize('si,ci,expected',[(4,3,[3,4,5,6]),(7,5,[5,6]),(2,1,[1,2,3,4,5,6])])
def test_exact_physical_consumer_invalidation(db_session,fixture,si,ci,expected):
    p=plan(fixture);p['keyframes'][si-1]['image_url']='/old.png'
    for c in p['clip_plan']:c['video_url']=f'/other-{c["clip_index"]}.mp4'
    save(db_session,fixture,p);consumer(db_session,fixture,ci,si,'/old.png',ordinary=si==2);before=plan(fixture)
    direct=commit_visual_state_image(db_session,fixture,'/new.png',frame_index=si-2,expected_provenance=state_provenance(fixture,si));db_session.commit()
    after=plan(fixture);assert direct=={ci}
    assert [c['clip_index'] for c in after['clip_plan'] if c.get('video_url') is None]==expected
    assert after['clip_plan_revision']==2
    assert [(c['capability'],c['selected_temporal_target_ids']) for c in after['clip_plan']]==[(c['capability'],c['selected_temporal_target_ids']) for c in before['clip_plan']]
    assert db_session.query(Task).count()==1


@pytest.mark.parametrize('si',[2,4,7])
def test_first_image_and_eligibility_no_false_invalidation(db_session,fixture,si):
    fixture.video_url='/assembly.mp4';db_session.commit()
    commit_visual_state_image(db_session,fixture,'/new.png',frame_index=si-2,expected_provenance=state_provenance(fixture,si));db_session.commit()
    assert fixture.video_url=='/assembly.mp4'


def test_active_physical_consumer_conflict_atomic(db_session,fixture):
    p=plan(fixture);p['keyframes'][3]['image_url']='/old.png';save(db_session,fixture,p)
    consumer(db_session,fixture,3,4,'/old.png',status='running');before=(fixture.video_director_plan,fixture.keyframes)
    with pytest.raises(CanonicalExecutionConflict):
        commit_visual_state_image(db_session,fixture,'/new.png',frame_index=2,expected_provenance=state_provenance(fixture,4))
    assert (fixture.video_director_plan,fixture.keyframes)==before


@pytest.mark.asyncio
async def test_upload_replace_recovery_share_anchor_commit(db_session,fixture,tmp_path,monkeypatch):
    from app.services import shot_keyframe_service as km, task_service as tm
    monkeypatch.setattr(km.file_storage,'base_dir',tmp_path);service=ShotKeyframeService()
    ok,url,_=await service.upload_keyframe_image(db_session,fixture.id,2,b'png','image.png')
    assert ok and plan(fixture)['keyframes'][3]['image_url']==url and plan(fixture)['temporal_anchors'][0]['image_url']==url
    ok,url,_=await service.replace_keyframe_image(db_session,fixture.id,2,'/replace.png')
    assert ok and plan(fixture)['temporal_anchors'][0]['image_url']=='/replace.png'
    t=task(db_session,fixture,4,id='recovery')
    monkeypatch.setattr(tm.file_storage,'download_image',AsyncMock(return_value=str(tmp_path/'recovered.png')))
    monkeypatch.setattr(tm,'local_path_to_url',lambda _: '/recovered.png')
    service=TaskService();service.comfyui_service=SimpleNamespace(client=SimpleNamespace(_parse_outputs=lambda *a:{'success':True,'image_url':'mock://image'}))
    assert await service._recover_completed_keyframe_prompt(t,{'outputs':{'1':{}}},db_session)
    assert t.status=='completed' and plan(fixture)['temporal_anchors'][0]['image_url']=='/recovered.png'
    assert json.loads(fixture.keyframes)[2]['image_url']=='/recovered.png'


@pytest.mark.asyncio
async def test_recovery_old_task_rejected_before_download(db_session,fixture,monkeypatch):
    from app.services import task_service as module
    t=task(db_session,fixture,4,revision=1);download=AsyncMock();monkeypatch.setattr(module.file_storage,'download_image',download)
    with pytest.raises(CanonicalExecutionConflict):await TaskService()._recover_completed_keyframe_prompt(t,{'outputs':{'1':{}}},db_session)
    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_generation_stamps_and_reuses_task(db_session,fixture,monkeypatch):
    from app.services import shot_keyframe_service as module
    enqueue=MagicMock();monkeypatch.setattr(module.worker_manager,'worker',lambda _:SimpleNamespace(enqueue=enqueue))
    service=ShotKeyframeService();ok,tid,_=await service.generate_keyframe_image(db_session,fixture.id,2)
    assert ok and json.loads(db_session.get(Task,tid).metadata_json)['canonical_image_provenance']==state_provenance(fixture,4)
    ok,tid2,_=await service.generate_keyframe_image(db_session,fixture.id,2)
    assert ok and tid2==tid and enqueue.call_count==1
    p=plan(fixture);p['clip_plan_revision']=3;save(db_session,fixture,p)
    with pytest.raises(CanonicalExecutionConflict):await service.generate_keyframe_image(db_session,fixture.id,2)
    assert enqueue.call_count==1


def test_image_ready_still_waits_previous(db_session,fixture,tmp_path):
    image=tmp_path/'ready.png';image.write_bytes(b'png')
    commit_visual_state_image(db_session,fixture,str(image),frame_index=2,expected_provenance=state_provenance(fixture,4));db_session.commit()
    required=project_required_execution_images(fixture,plan(fixture));c3=project_clip_execution_readiness(db_session,fixture,plan(fixture),required)[2]
    assert c3['images_ready'] and not c3['ready'] and c3['code']=='WAITING_PREVIOUS_AV' and c3['previous_clip_index']==2


def test_endpoint_existing_image_path_zero_video(client,db_session,fixture,monkeypatch):
    from app.services import shot_keyframe_service as module
    monkeypatch.setattr(module.worker_manager,'worker',lambda _:SimpleNamespace(enqueue=MagicMock()))
    response=client.post('/api/novels/novel/chapters/chapter/shots/shot/video-director/prepare-required-images',json={'clip_plan_revision':2})
    assert response.status_code==200,response.text
    assert [i['status'] for i in response.json()['data']['items']]==['READY','QUEUED','QUEUED']
    tasks=db_session.query(Task).all();assert len(tasks)==2 and all(t.type=='keyframe_image' and t.parent_task_id is None for t in tasks)


def test_projection_of_unmarked_history_does_not_invent_preparation(db_session,fixture):
    p=plan(fixture);p['clip_plan_validation'].pop('temporal_contract');p['clip_plan'][0].pop('visual_state_indexes');save(db_session,fixture,p)
    assert project_required_execution_images(fixture,p)==[]


def test_roundtrip_projection_not_persisted(db_session,fixture):
    from app.repositories.shot_repository import ShotRepository
    repo=ShotRepository(db_session);response=repo.to_response(fixture)
    assert response['videoDirectorPlan']['required_execution_images']
    repo.update(fixture,video_director_plan=response['videoDirectorPlan'])
    assert 'required_execution_images' not in plan(fixture) and 'clip_execution_readiness' not in plan(fixture)


def test_superseded_attempt_cannot_overwrite_uploaded_image(db_session,fixture):
    t=task(db_session,fixture,4);expected=state_provenance(fixture,4)
    commit_visual_state_image(db_session,fixture,'/manual.png',frame_index=2,expected_provenance=expected);db_session.commit()
    with pytest.raises(CanonicalExecutionConflict,match='ATTEMPT_CHANGED'):
        commit_visual_state_image(db_session,fixture,'/old-task.png',frame_index=2,expected_provenance=expected,task_id=t.id)
    assert plan(fixture)['keyframes'][3]['image_url']=='/manual.png'


@pytest.mark.asyncio
async def test_ready_state_repairs_missing_anchor_without_generation(db_session,fixture,tmp_path):
    image=tmp_path/'state.png';image.write_bytes(b'image');p=plan(fixture);p['keyframes'][3]['image_url']=str(image);save(db_session,fixture,p)
    submit=AsyncMock();start=AsyncMock()
    result=await prepare_required_images(db_session,fixture,2,submit,start,clip_indexes=[3])
    assert result[0]['status']=='READY' and plan(fixture)['temporal_anchors'][0]['image_url']==str(image)
    submit.assert_not_awaited();start.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['upload','replace','recovery'])
async def test_each_completion_path_invalidates_exact_consumer(db_session,fixture,tmp_path,monkeypatch,path):
    from app.services import shot_keyframe_service as km, task_service as tm
    p=plan(fixture);p['keyframes'][3]['image_url']='/old.png'
    for c in p['clip_plan']:c['video_url']=f'/current-{c["clip_index"]}.mp4'
    save(db_session,fixture,p);consumer(db_session,fixture,3,4,'/old.png')
    if path=='upload':
        monkeypatch.setattr(km.file_storage,'base_dir',tmp_path)
        ok,_,message=await ShotKeyframeService().upload_keyframe_image(db_session,fixture.id,2,b'png','image.png');assert ok,message
    elif path=='replace':
        ok,_,message=await ShotKeyframeService().replace_keyframe_image(db_session,fixture.id,2,'/new.png');assert ok,message
    else:
        t=task(db_session,fixture,4)
        monkeypatch.setattr(tm.file_storage,'download_image',AsyncMock(return_value=str(tmp_path/'new.png')))
        monkeypatch.setattr(tm,'local_path_to_url',lambda _:'/new.png')
        service=TaskService();service.comfyui_service=SimpleNamespace(client=SimpleNamespace(_parse_outputs=lambda *a:{'success':True,'image_url':'mock://new'}))
        assert await service._recover_completed_keyframe_prompt(t,{'outputs':{'1':{}}},db_session)
    assert [c['clip_index'] for c in plan(fixture)['clip_plan'] if c.get('video_url') is None]==[3,4,5,6]


@pytest.mark.asyncio
async def test_main_preparation_completion_and_recovery_provenance(db_session,fixture,tmp_path,monkeypatch):
    from app.services import shot_image_service as main_module, task_service as tm
    t=task(db_session,fixture,1);t.status='running';db_session.commit()
    main_module._update_shot_image(db_session,'chapter',1,str(tmp_path/'main-new.png'),'/main-new.png',task_id=t.id)
    assert fixture.image_url=='/main-new.png' and fixture.image_task_id==t.id
    monkeypatch.setattr(tm.file_storage,'download_image',AsyncMock(return_value=str(tmp_path/'main-recover.png')))
    monkeypatch.setattr(tm,'local_path_to_url',lambda _:'/main-recover.png')
    service=TaskService();service.comfyui_service=SimpleNamespace(client=SimpleNamespace(_parse_outputs=lambda *a:{'success':True,'image_url':'mock://main'}))
    assert await service._recover_completed_shot_image_prompt(t,{'outputs':{'1':{}}},db_session)
    assert fixture.image_url=='/main-recover.png' and t.status=='completed'
    p=plan(fixture);p['clip_plan_revision']=3;save(db_session,fixture,p)
    with pytest.raises(CanonicalExecutionConflict):main_module._update_shot_image(db_session,'chapter',1,None,'/stale.png',task_id=t.id)
    assert fixture.image_url=='/main-recover.png'


@pytest.mark.asyncio
async def test_each_item_rechecks_readiness_after_previous_await(db_session,fixture,tmp_path):
    image=tmp_path/'concurrent.png';image.write_bytes(b'image');calls=[]
    async def submit(frame,provenance):
        calls.append(provenance['state_index'])
        commit_visual_state_image(db_session,fixture,str(image),frame_index=5,expected_provenance=state_provenance(fixture,7));db_session.commit()
        return 'new-KF4'
    results=await prepare_required_images(db_session,fixture,2,submit,AsyncMock())
    assert calls==[4] and [i['status'] for i in results]==['READY','QUEUED','READY']


@pytest.mark.parametrize('consumed',['legacy','anchor'])
def test_divergent_old_image_urls_still_invalidate_actual_manifest(db_session,fixture,consumed):
    p=plan(fixture);p['keyframes'][3]['image_url']='/canonical.png';p['temporal_anchors'][0]['image_url']='/anchor.png'
    frames=json.loads(fixture.keyframes);frames[2]['image_url']='/legacy.png';fixture.keyframes=json.dumps(frames);save(db_session,fixture,p)
    consumer(db_session,fixture,3,4,f'/{consumed}.png',ordinary=consumed=='legacy')
    direct=commit_visual_state_image(db_session,fixture,'/new.png',frame_index=2,expected_provenance=state_provenance(fixture,4));db_session.commit()
    assert direct=={3} and plan(fixture)['clip_plan'][2]['execution_status']=='PLANNED'


@pytest.mark.asyncio
async def test_start_adapter_preserves_history_and_old_physical_consumer(db_session,fixture,monkeypatch):
    from app.api import shots as api
    from app.repositories import NovelRepository, ChapterRepository, TaskRepository, ShotRepository, PromptTemplateRepository
    from app.schemas.shot import GenerateShotImageRequest
    fixture.image_url='/old-main.png';db_session.commit()
    consumer(db_session,fixture,1,1,'/old-main.png',ordinary=True)
    monkeypatch.setattr(api,'_build_shot_image_reference_readiness',lambda *a:{'available_reference_count':1,'manifest':[]})
    monkeypatch.setattr(api,'_resolve_shot_image_workflow_type',lambda *a:'shot')
    monkeypatch.setattr(api.TaskService,'validate_workflow_node_mapping',lambda *a:(True,None))
    monkeypatch.setattr(api,'_resolve_shot_image_prompt_text',AsyncMock(return_value=('mock prompt','mock template')))
    delete=MagicMock();enqueue=MagicMock()
    monkeypatch.setattr(api.file_storage,'delete_shot_image',delete);monkeypatch.setattr(api,'generate_shot_task',enqueue)
    provenance=state_provenance(fixture,1)
    result=await api._prepare_and_enqueue_shot_image_generation('novel','chapter',fixture.id,GenerateShotImageRequest(),db_session,
        NovelRepository(db_session),ChapterRepository(db_session),TaskRepository(db_session),
        SimpleNamespace(get_active_by_type=lambda _:SimpleNamespace(id='mock-workflow',name='mock')),
        ShotRepository(db_session),PromptTemplateRepository(db_session),SimpleNamespace(),canonical_image_provenance=provenance)
    tid=result['data']['taskId'];t=db_session.get(Task,tid)
    assert json.loads(t.metadata_json)['canonical_image_previous_url']=='/old-main.png'
    delete.assert_not_called();assert enqueue.call_count==1
    # A failed missing-main attempt cleared the Shot URL; retry retains the
    # old physical source snapshot rather than losing invalidation authority.
    t.status='failed';db_session.commit()
    retried=await api._prepare_and_enqueue_shot_image_generation('novel','chapter',fixture.id,GenerateShotImageRequest(),db_session,
        NovelRepository(db_session),ChapterRepository(db_session),TaskRepository(db_session),
        SimpleNamespace(get_active_by_type=lambda _:SimpleNamespace(id='mock-workflow',name='mock')),
        ShotRepository(db_session),PromptTemplateRepository(db_session),SimpleNamespace(),canonical_image_provenance=provenance)
    tid=retried['data']['taskId']
    assert json.loads(db_session.get(Task,tid).metadata_json)['canonical_image_previous_url']=='/old-main.png'
    delete.assert_not_called();assert enqueue.call_count==2
    direct=commit_visual_state_image(db_session,fixture,'/new-main.png',frame_index=None,expected_provenance=provenance,task_id=tid)
    db_session.commit();assert direct=={1} and plan(fixture)['clip_plan'][0]['execution_status']=='PLANNED'
    assert db_session.query(Task).filter(Task.type.like('%batch%')).count()==0


def test_dead_start_url_cannot_mask_prepared_main_image(db_session,fixture,tmp_path):
    p=plan(fixture);p['keyframes'][0]['image_url']='/dead-start.png';fixture.image_url=None;save(db_session,fixture,p)
    t=task(db_session,fixture,1);image=tmp_path/'new-main.png';image.write_bytes(b'image')
    commit_visual_state_image(db_session,fixture,str(image),frame_index=None,expected_provenance=state_provenance(fixture,1),task_id=t.id)
    db_session.commit();required=project_required_execution_images(fixture,plan(fixture),[t])
    assert required[0]['ready'] and required[0]['image_source']=='SHOT_IMAGE'
