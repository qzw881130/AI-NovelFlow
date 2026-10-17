"""Offline policy projection over saved production plans; no external generation."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.models.novel import Novel, Chapter, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.models.prompt_template import PromptTemplate
from app.services import h3_phase_b_pipeline as pipe, h3_single_stage_experiment as director
from app.services.effective_execution import project_effective_execution, projection_record, task_execution_projection
from app.services.clip_execution_compiler import compile_extend_clip, project_canonical_visual_references, get_canonical_execution_readiness
from app.services.required_visual_state_images import project_required_execution_images
from app.services.shot_video_service import _semantic_clip_prompt_context, clip_prompt_projection_metadata, reusable_clip_prompt
from app.services.video_director_ai import build_h3_video_prompt
from app.services.h3_native_prompt import dialogue_events, speaker_bindings
from app.services.comfyui.service import ComfyUIService
from app.services.comfyui.workflows import WorkflowBuilder
from app.utils.path_utils import url_to_local_path
from test_h3_phase_b_single_owned_state import offline_only, mock_decisions
from test_h3_phase_b_pipeline import FakeDirector, FakeComfy
from h3_language_fakes import language_response

ROOT = Path(__file__).parent / 'fixtures/h3_multi_keyframe_phase_b'


def saved_c6():
    return json.loads((ROOT / 'test3_shot1_c6_execution_policy.json').read_text())


def case(db, sample='c6', silent=False, policy='EXTEND_ONLY'):
    saved = saved_c6() if sample == 'c6' else json.loads((ROOT / f'test3_shot{sample}_c2_single_owned.json').read_text())
    plan = deepcopy(saved['plan'])
    ci = 6 if sample == 'c6' else 2
    # Older fixture omitted the plan anchor catalog; reuse its saved physical
    # manifest (5.5s original Story-local), without inventing any state or time.
    if sample == 2:
        plan['temporal_anchors'] = deepcopy(saved['execution_contract']['temporal_anchor_manifest']['anchors'])
    if silent:
        plan['dialogue_timeline_source'] = []
        for c in plan['clip_plan']:
            c['dialogue_assignment'] = []
    original = next(c for c in plan['clip_plan'] if c['clip_index'] == ci)
    projection = project_effective_execution(plan, original, policy)
    view = projection['effective_clip']
    novel = Novel(title='offline effective execution')
    db.add(novel); db.flush()
    chapter = Chapter(novel_id=novel.id, title='offline', number=1)
    db.add(chapter); db.flush()
    shot = Shot(**{k:v for k,v in saved['shot'].items() if k not in {'id','chapter_id'}},
                chapter_id=chapter.id, video_director_plan=json.dumps(plan, ensure_ascii=False))
    db.add(shot)
    db.add_all([Prop(novel_id=novel.id, **p) for p in saved['props']])
    template = PromptTemplate(name='offline selected template', type=pipe.TEMPLATE_TYPE, is_active=True,
                              is_system=True, template=director.PHASE_B_TEMPLATE.read_text())
    db.add(template); db.flush()
    previous = saved['previous_clip'] if sample == 'c6' else saved['execution_contract']['previous_clip']
    resources = {'references': deepcopy(saved['manifest']['references']), 'skipped_references': []}
    compiled = compile_extend_clip(shot, plan, view, plan['clip_plan_revision'], previous, resources)
    contract, manifest = compiled['execution_contract'], compiled['video_reference_manifest']
    contract['execution_projection'] = projection_record(projection)
    metadata = {'clip_index': ci, 'continuation_mode': policy, 'execution_projection': projection_record(projection),
                'capability': view['capability'], 'execution_contract': contract, 'execution_scope': 'CLIP', 'h3_prompt_pipeline':'phase_b'}
    context = _semantic_clip_prompt_context(plan, metadata, resolved_dialogue_timeline=plan['dialogue_timeline_source'])
    workflow = SimpleNamespace(**saved_c6()['workflow'])
    builder = asyncio.run(build_h3_video_prompt(db=db, novel=novel, shot=shot, selected_mode='MULTI_KEYFRAME',
        clip=context['clip'], workflow_capability={}, workflow_type=workflow.type, workflow_name=workflow.name,
        start_image_url=None, keyframes=context['keyframes'], transitions=context['transitions'],
        clip_dialogues=context['clip_dialogues'], reference_images=[], character_appearances=saved['character_appearances'],
        temporal_anchors=[], video_reference_manifest=manifest, previous_av_present=True,
        current_visual_state=next(s for s in plan['keyframes'] if s['index'] == original['carry_in_state_index']),
        resolved_dialogue_timeline=plan['dialogue_timeline_source'], input_only=True))
    previous_path = url_to_local_path(previous['result_url'])
    snapshot = pipe.runtime_snapshot(plan=plan, builder_input=builder, manifest=manifest, workflow=workflow,
        previous_path=previous_path, execution_contract=contract, shot_description=shot.description)
    task = Task(type='shot_video', name='offline policy', status='running', novel_id=novel.id,
                chapter_id=chapter.id, shot_id=shot.id, metadata_json=json.dumps(metadata))
    db.add(task); db.commit()
    args = dict(db=db, task=task, novel=novel, shot=shot, builder_input=builder, manifest=manifest,
                workflow=workflow, previous_path=previous_path, execution_contract=contract)
    return saved, plan, projection, snapshot, args, template


@pytest.mark.parametrize('sample', ['c6',1,2])
@pytest.mark.parametrize('silent', [False,True])
def test_saved_plans_effective_extend_full_offline_chain(db_session, sample, silent):
    saved, plan, projection, snapshot, args, template = case(db_session, sample, silent)
    before = deepcopy(plan)
    p = director.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
    assert p['status'] == 'PREPARED', p
    owned = [7,8] if sample == 'c6' else [3]
    assert [s['index'] for s in p['llm_input']['canonical']['owned_visual_states']] == owned
    assert p['llm_input']['canonical']['carry_in_visual_state']['index'] == (6 if sample == 'c6' else 2)
    assert p['llm_input']['clip']['capability'] == 'EXTEND'
    assert p['temporal_anchors'] == []
    assert [a['anchor_id'] for a in p['llm_input']['anchor_catalog']] == [f'KF{i}' for i in owned]
    assert len(p['picture_mapping']) == len(saved['manifest']['references'])
    assert p['llm_input']['subject_bindings'] == {b['subject']: b['name'] for b in snapshot['builder_input']['reference_binding_contract']['characters']}
    assert p['llm_input']['speaker_bindings'] == speaker_bindings(p['canonical'])
    if sample == 'c6':
        assert projection['planned_capability'] == 'TEMPORAL_EXTEND'
        assert projection['suppressed_temporal_anchor_ids'] == ['clip-6-KF8']
        assert snapshot['physical_evidence']['previous_clip']['clip_index'] == 5
        assert p['continuation']['source_sha256'] == '90458e78d521a689dcfc95cd84da1cfa0b9347132578c5a2618f2a8052010ad3'
        response = deepcopy(saved['original_decisions'])
        response['anchors'] = [a for a in response['anchors'] if not a['id'].startswith('clip-')]
        # Contract-only response; no claim of director quality for the new mode.
        response['detailed_description'] = '<Subject 1>按 Canonical 范围完成动作。' + ''.join(f'[[SPEECH_{i}]]' for i in range(1, len(p['canonical'])+1))
        response['overall_soundscape'] = '<Subject 1>的衣料声及场景环境声。'
    else:
        response = mock_decisions(p)
    if silent:
        response['dialogue_events'] = []
        for a in response['anchors']: a['arrival_relation'] = None
    llm = FakeDirector(response)
    prompt = asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    record = json.loads(args['task'].metadata_json)['h3_phase_b']
    assert len(llm.calls) == 1 and record['preflight']['passed']
    assert record['version'] == 'H3_PHASE_B_LIMITED_V3'
    assert [(e['speaker'],e['exact_dialogue']) for e in dialogue_events(prompt)] == [(e['speaker'],e['exact_dialogue']) for e in p['canonical']]
    assert '[[SPEECH_' not in prompt
    if silent: assert 'All characters remain silent' in prompt and not p['llm_input']['speech_slots']
    paths = [r.get('local_path') or url_to_local_path(r['image_url']) for r in args['manifest']['references']]
    duration, anchors, manifest, paths = pipe.apply_execution(args['task'], 9.2, args['manifest'], paths)
    assert anchors['anchors'] == []
    assert all(r.get('source_keyframe_index') not in projection['suppressed_state_indexes'] for r in manifest['references'])
    service = object.__new__(ComfyUIService); service.builder = WorkflowBuilder(); service.client = FakeComfy()
    wf = args['workflow']; graph_before = wf.workflow_json
    output = asyncio.run(service.generate_video_continuation_with_workflow(
        prompt, wf.workflow_json, json.loads(wf.node_mapping), args['previous_path'], duration, 'offline-only',
        capability=wf.type, reference_image_paths=paths, anchors=[], require_native_output=True,
        before_submit=lambda graph, uploads: pipe.verify_submission(args['task'],wf,graph,uploads,args['previous_path'])))
    assert output['success'], output
    assert len(service.client.posts)==1 and len(service.client.uploads)==len(paths)
    graph=service.client.posts[0]
    assert not any(n['class_type']=='CustomKeyframes' for n in graph.values())
    assert wf.workflow_json == graph_before and plan == before
    assert json.loads(args['task'].metadata_json)['h3_phase_b']['submission_preflight']['passed']
    assert task_execution_projection(plan, next(c for c in plan['clip_plan'] if c['clip_index']==projection['planned_clip']['clip_index']),json.loads(args['task'].metadata_json)) == projection


@pytest.mark.parametrize('mode', ['AUTO','EXTEND_ONLY'])
@pytest.mark.parametrize('ci', [1,2,6])
def test_modes_and_original_canonical_unchanged(mode,ci):
    saved=saved_c6();plan=saved['plan'];clip=plan['clip_plan'][ci-1];before=deepcopy(plan)
    result=project_effective_execution(plan,clip,mode)
    assert result['effective_capability']==('EXTEND' if mode=='EXTEND_ONLY' and clip['capability']=='TEMPORAL_EXTEND' else clip['capability'])
    assert result['effective_clip']['visual_state_indexes']==clip['visual_state_indexes']
    assert result['effective_clip']['carry_in_state_index']==clip['carry_in_state_index']
    assert plan==before
    if mode=='AUTO': assert result['effective_clip']==clip


def test_cut_and_invalid_policy_or_selection_never_silently_reinterpreted():
    plan=saved_c6()['plan'];clip=deepcopy(plan['clip_plan'][5]);clip.update(capability='GENERATE',continuity_to_previous='CUT')
    assert project_effective_execution(plan,clip,'EXTEND_ONLY')['effective_capability']=='GENERATE'
    with pytest.raises(ValueError,match='CONTINUATION_MODE_INVALID'):project_effective_execution(plan,clip,'unknown')
    clip['capability']='TEMPORAL_EXTEND'
    with pytest.raises(ValueError,match='CONTINUATION_PLAN_MODE_MISMATCH'):project_effective_execution(plan,clip,'EXTEND_ONLY')
    clip=deepcopy(plan['clip_plan'][5]);clip['visual_state_indexes']=[7]
    with pytest.raises(ValueError,match='TEMPORAL_STATE_MISMATCH'):project_effective_execution(plan,clip,'EXTEND_ONLY')
    clip=deepcopy(plan['clip_plan'][5]);clip['temporal_anchor_ids']=[]
    with pytest.raises(ValueError,match='SELECTION_MISMATCH'):project_effective_execution(plan,clip,'EXTEND_ONLY')


def test_suppressed_image_cannot_fall_back_to_picture_and_readiness_does_not_require_it():
    saved=saved_c6();plan=saved['plan'];clip=plan['clip_plan'][5];shot=SimpleNamespace(**saved['shot'],video_director_plan=json.dumps(plan),keyframes='[]')
    assert any(i['state_index']==8 for i in project_required_execution_images(shot,plan,clip_indexes=[6]))
    assert project_required_execution_images(shot,plan,clip_indexes=[6],continuation_mode='EXTEND_ONLY')==[]
    assert get_canonical_execution_readiness(shot,plan,[clip],continuation_mode='EXTEND_ONLY')['ready']
    view=project_effective_execution(plan,clip,'EXTEND_ONLY')['effective_clip']
    refs=project_canonical_visual_references(shot,plan,view,resource_references=saved['manifest'])['references']
    assert refs == [{**r,'slot':i} for i,r in enumerate(saved['manifest']['references'],1)]
    # Merely clearing temporal inputs would leak KF8 into an ordinary Picture.
    broken=deepcopy(view);broken.pop('execution_projection')
    assert any(r.get('source_keyframe_index')==8 for r in project_canonical_visual_references(shot,plan,broken)['references'])


def test_historical_auto_and_frozen_policy_reject_changed_recovery():
    plan=saved_c6()['plan'];clip=plan['clip_plan'][5]
    assert task_execution_projection(plan,clip,{})['effective_capability']=='TEMPORAL_EXTEND'
    p=project_effective_execution(plan,clip,'EXTEND_ONLY');meta={'continuation_mode':'EXTEND_ONLY','execution_projection':projection_record(p),'capability':'EXTEND'}
    assert task_execution_projection(plan,clip,meta)==p
    with pytest.raises(ValueError,match='EXECUTION_PROJECTION_CHANGED'):task_execution_projection(plan,clip,{**meta,'continuation_mode':'AUTO'})
    with pytest.raises(ValueError,match='EXECUTION_PROJECTION_MISSING'):task_execution_projection(plan,clip,{'continuation_mode':'EXTEND_ONLY'})


def test_cached_inputs_are_policy_specific_even_when_mode_does_not_change(db_session):
    from test_h3_phase_b_pipeline import make_case
    snap,args,template=make_case(db_session,'shot12_c1_generate')
    p=director.prepare_multi_keyframe_phase_b(snap,runtime=True)
    assert p['status']=='PREPARED'
    b=deepcopy(p);b['execution_projection']['continuation_mode']='EXTEND_ONLY'
    assert pipe.input_fingerprint(p,template)!=pipe.input_fingerprint(b,template)
    plan=saved_c6()['plan'];clip=plan['clip_plan'][1];view=project_effective_execution(plan,clip,'EXTEND_ONLY')['effective_clip']
    stored=deepcopy(clip);stored['video_prompt']='old';stored['prompt_projection']=clip_prompt_projection_metadata(plan,clip,{'status':'LEGACY_MISSING'},'old')
    assert reusable_clip_prompt(plan,view,'old',{},stored['prompt_projection']) is False


@pytest.mark.parametrize('silent',[False,True])
@pytest.mark.parametrize('mode',['AUTO','EXTEND_ONLY'])
def test_generate_policy_prepare_compile_preflight(db_session,silent,mode):
    from test_h3_phase_b_pipeline import make_case,saved
    snap,args,_=make_case(db_session,'shot12_c1_generate',silent=silent)
    plan=snap['canonical_plan'];clip=plan['clip_plan'][0]
    projection=project_effective_execution(plan,clip,mode)
    args['execution_contract']['execution_projection']=projection_record(projection)
    response=saved('shot12_c1_generate','_mock_response')
    if silent:
        response['dialogue_events']=[]
        response['detailed_description']='<Subject 1>保持沉默，完成 Canonical 动作。'
        for a in response['anchors']:a['arrival_relation']=None
    llm=FakeDirector(response)
    prompt=asyncio.run(pipe.build_phase_b_prompt(**args,llm=llm))
    record=json.loads(args['task'].metadata_json)['h3_phase_b']
    assert record['preflight']['passed'] and record['director_input']['clip']['capability']=='GENERATE'
    assert len(dialogue_events(prompt))==(0 if silent else 6)


@pytest.mark.parametrize('damage',['no_owned','foreign_reference','previous_missing','source_state_changed'])
def test_strict_authority_checks_not_relaxed(db_session,damage):
    _,plan,projection,snap,args,_=case(db_session)
    if damage=='no_owned':
        # This Clip has real targets in its interval. Deleting their ownership
        # cannot disguise it as a legitimate carry-only continuation.
        for container in [snap['canonical_plan']['clip_plan']]:
            c=next(c for c in container if c['clip_index']==6);c['visual_state_indexes']=[];c['capability']='EXTEND';c['requires_temporal_control']=False;c['temporal_anchor_ids']=[]
        snap['physical_evidence'].pop('execution_projection')
        snap['builder_input']['clip'].update(visual_state_indexes=[],capability='EXTEND')
        snap['builder_input']['visual_controls']=[]
        expected='CANONICAL_STATE_SCOPE_MISMATCH'
    elif damage=='foreign_reference':
        snap['reference_manifest']['references'][0]['image_url']=projection['suppressed_image_urls'][0]
        expected='SUPPRESSED_TEMPORAL_REFERENCE_RETURNED'
    elif damage=='previous_missing':
        snap['previous_video_path']=None
        expected='Previous'
    else:
        snap['builder_input']['visual_controls'][0]['description']='illicit replacement'
        expected='SAVED_STATES_MISMATCH'
    for k in snap['source']['hashes']:snap['source']['hashes'][k]=director._snapshot_digest(snap[k])
    p=director.prepare_multi_keyframe_phase_b(snap,runtime=True)
    assert p['status']=='NOT_COVERED',p
    if damage!='previous_missing':assert expected in str(p['reasons']),p


@pytest.mark.parametrize("cancel_during_upload",[False,True])
def test_actual_api_real_persisted_worker_and_policy_replay(db_session,db_engine,monkeypatch,cancel_during_upload):
    from sqlalchemy.orm import sessionmaker
    from app.api import shots as api
    from app.models.workflow import Workflow
    from app.models.novel import Character
    from app.models.background_job import BackgroundJob
    from app.repositories import NovelRepository,ChapterRepository,ShotRepository,TaskRepository,WorkflowRepository
    from app.services import shot_video_service as video,background_workers
    from app.services.background_workers import WorkerManager
    from app.services.llm_service import LLMService
    saved,plan,projection,snapshot,args,_=case(db_session)
    shot,novel=args['shot'],args['novel'];db_session.delete(args['task'])
    wf=args['workflow'];db_session.add(Workflow(**vars(wf),is_active=True))
    db_session.add_all([Character(novel_id=novel.id,name=n,appearance=a) for n,a in saved['character_appearances'].items()])
    db_session.commit();shot_id=shot.id
    factory=sessionmaker(bind=db_engine,autoflush=False)
    manager=WorkerManager(factory)
    monkeypatch.setattr(background_workers,'worker_manager',manager)
    monkeypatch.setattr(video,'worker_manager',manager)
    monkeypatch.setattr(video,'SessionLocal',factory)
    monkeypatch.setattr(video,'_queued_shot_video_task_ids',set())
    resources={'references':saved['manifest']['references']}
    previous={**saved['previous_clip'],'local_path':args['previous_path']}
    for module in (api,video):
        monkeypatch.setattr(module,'resolve_clip_reference_resources',lambda *a,**k:deepcopy(resources))
        monkeypatch.setattr(module,'resolve_extend_previous_av',lambda *a,**k:deepcopy(previous))
    response=deepcopy(saved['original_decisions']);response['anchors']=[a for a in response['anchors'] if a['id'] in ['KF7','KF8']]
    response['detailed_description']='<Subject 1>依照 Canonical 完成本片段动作。[[SPEECH_1]][[SPEECH_2]]'
    response['overall_soundscape']='<Subject 1>的衣料声及环境声。'
    llm=FakeDirector(response)
    async def director_with_language(**kw):
        llm.content = language_response(json.loads(kw['user_content']), response)
        return await llm.chat_completion(**kw)
    monkeypatch.setattr(LLMService,'chat_completion',lambda self,**kw:director_with_language(**kw))
    service=object.__new__(ComfyUIService);service.builder=WorkflowBuilder();service.client=FakeComfy()
    monkeypatch.setattr(video,'ComfyUIService',lambda:service)
    saves=[]
    async def save(result,task,*pos,**kw):
        saves.append(kw);task.status='completed';task.result_url='/offline-result.mp4';pos[3].commit()
    monkeypatch.setattr(video,'_save_generated_video',save)
    async def run():
        try:
            from app.schemas.shot import GenerateVideoDirectorClipRequest
            result=await api.generate_video_director_clip(novel.id,shot.chapter_id,shot.id,6,
                GenerateVideoDirectorClipRequest(continuation_mode='EXTEND_ONLY',clip_plan_revision=plan['clip_plan_revision']),
                NovelRepository(db_session),ChapterRepository(db_session),TaskRepository(db_session),WorkflowRepository(db_session),ShotRepository(db_session))
            if cancel_during_upload:
                upload=service.client.upload_image
                async def cancel_upload(path):
                    with factory() as cancel_db:
                        cancel_db.get(Task,result['data']['taskId']).status='cancelled';cancel_db.commit()
                    return await upload(path)
                service.client.upload_image=cancel_upload
            await asyncio.wait_for(manager.worker('shot_video')._queue.join(),30)
            db_session.expire_all();task=db_session.get(Task,result['data']['taskId'])
            job=db_session.query(BackgroundJob).filter_by(task_id=task.id).one()
            if cancel_during_upload:
                assert task.status=='cancelled' and not service.client.posts and not saves
                return
            assert task.status=='completed',task.error_message
            assert job.status=='completed' and job.attempts==1
            meta=json.loads(task.metadata_json)
            assert meta['execution_projection']==projection_record(projection)
            assert meta['capability']=='EXTEND' and meta['planned_capability']=='TEMPORAL_EXTEND'
            assert meta['h3_phase_b']['submission_preflight']['passed']
            assert meta['h3_phase_b']['director_input']['clip']['capability']=='EXTEND'
            assert json.loads(job.payload_json)['clip_metadata']['continuation_mode']=='EXTEND_ONLY'
            assert len(llm.calls)==len(service.client.posts)==len(saves)==1
            assert not saves[0]['update_shot_result']
            assert json.loads(db_session.get(Shot,shot_id).video_director_plan)['clip_plan'][5]['capability']=='TEMPORAL_EXTEND'
        finally:await manager.stop()
    asyncio.run(run())


def test_required_image_preparation_uses_policy_without_creating_suppressed_materials(db_session,monkeypatch):
    from app.services.required_visual_state_images import prepare_required_images
    from app.services import required_visual_state_images as images
    _,plan,projection,_,args,_=case(db_session)
    # Explicit missing-image simulation. The policy must not request KF8 again.
    monkeypatch.setattr(images,'image_exists',lambda _:False)
    calls=[]
    async def forbidden(*a,**kw):calls.append((a,kw));pytest.fail('suppressed image requested')
    result=asyncio.run(prepare_required_images(db_session,args['shot'],plan['clip_plan_revision'],forbidden,forbidden,
                                             clip_indexes=[6],continuation_mode='EXTEND_ONLY'))
    assert result==[] and calls==[]
    assert any(i['state_index']==8 and not i['ready'] for i in images.project_required_execution_images(args['shot'],plan,clip_indexes=[6]))
    assert json.loads(args['shot'].video_director_plan)==plan


def test_readonly_shot_response_exposes_policy_without_changing_planned_capability(db_session):
    from app.repositories.shot_repository import ShotRepository
    _,plan,projection,_,args,_=case(db_session)
    shot=args['shot'];stored=shot.video_director_plan
    repo=ShotRepository(db_session)
    auto=repo.to_response(shot,include_ai_history=False)['videoDirectorPlan']
    effective=repo.to_response(shot,include_ai_history=False,continuation_mode='EXTEND_ONLY')['videoDirectorPlan']
    assert auto['clip_plan'][5]['capability']==effective['clip_plan'][5]['capability']=='TEMPORAL_EXTEND'
    assert auto['execution_policy']['clips'][5]['effective_capability']=='TEMPORAL_EXTEND'
    assert effective['execution_policy']['clips'][5]==projection_record(projection)
    assert any(i['state_index']==8 for i in auto['required_execution_images'])
    assert not any(i['state_index']==8 for i in effective['required_execution_images'])
    assert shot.video_director_plan==stored
    assert effective['keyframes']==plan['keyframes'] and effective['transitions']==plan['transitions']
