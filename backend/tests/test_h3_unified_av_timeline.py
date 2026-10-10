"""Execution facts, prompt/time agreement and actual workflow duration propagation."""
import copy
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from app.services import h3_execution_optimizer as opt
from app.services.shot_video_service import _apply_h3_execution_duration
from app.services.comfyui.workflows import WorkflowBuilder


@pytest.fixture
def case(monkeypatch):
    monkeypatch.setattr(opt, 'previous_video_frames', lambda _: [])
    raw = '''duration: 5s
<Subject 1> is A, stable face.
<Subject 2> is B, stable face.
KF1 — START — Clip-local 0s — TEXT_ONLY. A remains seated; B stands to the left; empty hands.
KF2 — END — Clip-local 4.9s — TEXT_ONLY. A looks at B's open empty hands; both remain in frame.
D1:
  speaker: <Subject 1>
  start_time: 1s
  end_time: 2s
  exact_dialogue: 问？
  execution: Only <Subject 1> vocalizes with synchronized lips; <Subject 2> is a silent listener without speech-like mouth movement.
D2:
  speaker: <Subject 2>
  start_time: 2.2s
  end_time: 3.7s
  exact_dialogue: 答。
  execution: Only <Subject 2> vocalizes with synchronized lips; <Subject 1> is a silent listener without speech-like mouth movement.
'''
    runtime, images = opt.build_runtime_input(raw, 'SINGLE_FRAME', {'clip_index': 1, 'planned_duration': 5})
    phases = [
        {'id':'R','type':'READINESS','start':0,'end':0.8,'description':'Settle both bodies and prepare D1.'},
        {'id':'C','type':'CAMERA','start':0,'end':5.2,'description':'Continuous gentle travel from KF1 to KF2 with both subjects readable.'},
        {'id':'V1','type':'ATTENTION','start':0.8,'end':1.8,'description':'<Subject 1> owns D1; <Subject 2> listens.'},
        {'id':'H','type':'HANDOFF','start':1.8,'end':2.3,'description':'D1 to D2: <Subject 1> closes speech mouth; <Subject 2> prepares without speaking.'},
        {'id':'V2','type':'ATTENTION','start':2.3,'end':3.8,'description':'<Subject 2> owns D2 while <Subject 1> listens.'},
        {'id':'A','type':'ACTION','start':3.8,'end':5.2,'description':'Complete the existing empty-hand gesture into KF2.'},
        {'id':'F','type':'FINAL_SETTLE','start':5.2,'end':6,'description':'Hold KF2 with empty hands and no new human voice.'},
    ]
    prompt = """subject_definitions:
<Subject 1> is A, with a stable face.
<Subject 2> is B, with a stable face.
summary:
A 6-second continuous ensemble shot.
retention_analysis:
The canonical visual states preserve clothing, pose, blocking, floor positions and empty hands. Physical identity and faces remain distinct.
detailed_description:
Maintain established floor positions. Begin with <Subject 1> seated and <Subject 2> standing to the left with empty hands. <Subject 1> remains seated throughout the camera's gentle movement. The camera gives his face and mouth a readable view while the other person listens with relaxed closed lips.
<Subject 1> (S1) asks, <d>[Chinese] 问？</d>
<Subject 1> closes his lips and listens. A small lateral camera drift transfers emphasis from <Subject 1> to <Subject 2>, clearing a readable face and mouth while both keep their established positions. All other visible characters listen naturally with relaxed closed lips and no speech-like articulation.
With that view established, <Subject 2> (S2) replies, <d>[Chinese] 答。</d>
Finish with A looking at B's open empty hands; both remain in frame. Hold the quiet ending naturally.
overall_soundscape:
Quiet room ambience.
non_diegetic_music:
N/A
"""
    output = {'optimized_prompt':prompt, 'authority_echo':runtime['immutable_authority'], 'risks':[], 'changes':[], 'timing_recommendations':[],
        'av_timeline': {'original_duration':5, 'optimized_duration':6, 'duration_delta':1, 'duration_changed':True, 'reason':'Budget meaningful handoff, gesture completion and final settling.',
            'dialogue_events':[{'id':'D1','speaker':'<Subject 1>','original_start':1,'original_end':2,'duration':1,'optimized_start':0.8,'optimized_end':1.8},
                {'id':'D2','speaker':'<Subject 2>','original_start':2.2,'original_end':3.7,'duration':1.5,'optimized_start':2.3,'optimized_end':3.8}],
            'handoffs':[{'from':'D1','to':'D2','from_subject':'<Subject 1>','to_subject':'<Subject 2>','original_gap':0.2,'optimized_gap':0.5,'reason':'Clear ownership before reply','strategy':'Close previous speaking mouth, shift gaze and prepare reply.',
                'complexity':'MEDIUM','complexity_reasoning':'Gaze and listener release; both faces already visible in shared framing.',
                'spatial_relation':'Seated center to standing left','depth_relation':'Shared readable depth',
                'visual_handoff_required':True,'camera_handoff_required':True,
                'prompt_evidence': {
                    'release': '<Subject 1> closes his lips and listens.',
                    'acquisition': 'A small lateral camera drift transfers emphasis from <Subject 1> to <Subject 2>, clearing a readable face and mouth while both keep their established positions.',
                    'listeners': 'All other visible characters listen naturally with relaxed closed lips and no speech-like articulation.',
                    'dialogue_entry': 'With that view established, '},
                'camera_strategy':'Shift camera emphasis from seated A to standing B while preserving their positions.',
                'previous_speaker_release':'A closes speech mouth and listens before the reply.',
                'next_speaker_readiness':'B is visible, identifiable and lip-ready before D2 begins.'}],
            'anchors':[{'id':'KF1','original_time':0,'optimized_time':0,'delta':0,'visual_state_changed':False,'reason':'Retain start','prompt_excerpt':'Begin with <Subject 1> seated and <Subject 2> standing to the left with empty hands.'},
                {'id':'KF2','original_time':4.9,'optimized_time':5.2,'delta':0.3,'visual_state_changed':False,'reason':'Allow gesture completion and settling','prompt_excerpt':"Finish with A looking at B's open empty hands; both remain in frame."}],
            'execution_phases': phases}}
    return raw, runtime, output


def audit(case, output=None):
    raw,runtime,default = case
    return opt.check_authority(raw, output or default, runtime['immutable_authority'], runtime['initial_execution_timing'], runtime['duration_limits'])


def record(case):
    return {'status':'OPTIMIZED', 'optimized_prompt':case[2]['optimized_prompt'], 'output':case[2], 'authority_check':audit(case)}


def test_joint_retiming_preserves_facts_and_applies_duration(case):
    result=audit(case)
    assert result['passed'], result['blocking_findings']
    assert 'start_time' not in case[1]['immutable_authority']['dialogue_events'][0]
    assert 'time' not in case[1]['immutable_authority']['visual_anchor_order'][0]
    assert case[1]['initial_execution_timing']['duration']==5
    assert opt.effective_execution_duration(5,record(case))=={'original_duration':5,'optimized_duration':6,'effective_duration':6.0,'duration_source':'H3_PROMPT_OPTIMIZER'}


def test_continuous_camera_handoff_can_rebalance_between_unchanged_anchors(case):
    output=copy.deepcopy(case[2])
    previous=output['av_timeline']['execution_phases'][1]['description']
    continuous='Continuous gentle lateral drift clears the foreground and makes the next speaker primary before D2; return smoothly to the unchanged KF2 composition.'
    output['av_timeline']['execution_phases'][1]['description']=continuous
    output['optimized_prompt']=output['optimized_prompt'].replace(previous,continuous)
    assert audit(case,output)['passed']
    assert 'VISIBILITY_ADAPTIVE_CAMERA' in case[1]['execution_flexibility']['inter_anchor_camera_path']
    assert output['av_timeline']['anchors']==case[2]['av_timeline']['anchors']
    assert output['authority_echo']['visual_anchor_order']==case[1]['immutable_authority']['visual_anchor_order']
    assert not opt.anchor_declarations(output['optimized_prompt'])


@pytest.mark.parametrize('complexity',['LOW','MEDIUM','HIGH'])
def test_reasoning_category_does_not_trigger_a_python_gap_preset(case,complexity):
    output=copy.deepcopy(case[2])
    output['av_timeline']['handoffs'][0].update(complexity=complexity,complexity_reasoning='Visual preparation completes concurrently before the gap; release and acquired readiness explain the remaining silence.')
    assert audit(case,output)['passed']
    assert output['av_timeline']['handoffs'][0]['optimized_gap']==0.5


@pytest.mark.parametrize('field,value',[
    ('complexity','unknown'),('visual_handoff_required','false'),('camera_handoff_required',1),
    ('camera_strategy',{}),('next_speaker_readiness',''),('spatial_relation',None),
])
def test_malformed_handoff_extension_is_not_silently_accepted(case,field,value):
    output=copy.deepcopy(case[2]);output['av_timeline']['handoffs'][0][field]=value
    assert 'handoff_reasoning_schema' in audit(case,output)['blocking_findings']


def test_historical_handoff_is_inspectable_with_missing_reasoning_warning(case):
    output=copy.deepcopy(case[2])
    handoff=output['av_timeline']['handoffs'][0]
    for field in ['complexity','complexity_reasoning','spatial_relation','depth_relation','visual_handoff_required',
                  'camera_handoff_required','camera_strategy','previous_speaker_release','next_speaker_readiness']:
        handoff.pop(field)
    result=audit(case,output)
    assert not result['passed']  # Historical records stay readable, but cannot pass the new acquisition contract.
    assert 'speaker_switch_camera_evidence' in result['blocking_findings']
    assert any(w['code']=='HANDOFF_REASONING_MISSING' for w in result['warnings'])


@pytest.mark.parametrize('mutation,check',[
    (lambda o:o['av_timeline']['dialogue_events'][0].update(duration=0.9),'dialogue_timeline_matches_prompt_and_initial'),
    (lambda o:o['av_timeline']['dialogue_events'].reverse(),'dialogue_timeline_matches_prompt_and_initial'),
    (lambda o:o['av_timeline']['handoffs'].clear(),'all_speaker_handoffs_consistent'),
    (lambda o:o['av_timeline']['handoffs'][0].update(optimized_gap=0.2),'all_speaker_handoffs_consistent'),
    (lambda o:o['av_timeline']['handoffs'][0].update(from_subject='<Subject 2>'),'all_speaker_handoffs_consistent'),
    (lambda o:o['av_timeline']['anchors'][1].update(optimized_time=5.3),'anchor_ids_order_initial_delta'),
    (lambda o:o['av_timeline']['anchors'][1].update(visual_state_changed=True),'anchor_ids_order_initial_delta'),
    (lambda o:o['av_timeline']['anchors'].reverse(),'anchor_ids_order_initial_delta'),
    (lambda o:o['av_timeline']['execution_phases'][0].update(id='C'),'execution_phase_ids_unique'),
    (lambda o:o['av_timeline']['execution_phases'][0].update(start=-1),'execution_phases_inside_budget'),
    (lambda o:o.update(optimized_prompt=o['optimized_prompt']+'\nOld camera arrival at 4.9s.'),'timing_internal_only'),
    (lambda o:o.update(optimized_prompt=o['optimized_prompt'].replace('empty hands.', 'cloth in hands.')),'anchor_prompt_rendering'),
    (lambda o:o.update(optimized_prompt=o['optimized_prompt'].replace('A 6-second','A 5-second')),'prompt_duration_matches_timeline'),
    (lambda o:o['av_timeline']['dialogue_events'][1].update(optimized_start=1.5),'no_illegal_dialogue_overlap'),
])
def test_inconsistent_timeline_is_blocked(case,mutation,check):
    output=copy.deepcopy(case[2]);mutation(output)
    assert check in audit(case,output)['blocking_findings']


@pytest.mark.parametrize('value',[True, float('nan'), float('inf'), -1, 0, 3.99, 20.01, '6'])
def test_budget_is_finite_numeric_and_within_existing_cap(case,value):
    output=copy.deepcopy(case[2]);output['av_timeline']['optimized_duration']=value
    assert 'duration_within_workflow_and_20s' in audit(case,output)['blocking_findings']


def test_twenty_seconds_and_lower_workflow_limit():
    assert opt.workflow_duration_limits({'max_clip_duration':20})['maximum']==20
    assert opt.workflow_duration_limits({'max_clip_duration':12})['maximum']==12
    assert opt.workflow_duration_limits({'min_clip_duration':6})['minimum']==6


@pytest.mark.parametrize('enabled,status,expected',[(False,'OPTIMIZED',5),(True,'FALLBACK',5),(True,'OPTIMIZED',6)])
def test_worker_duration_priority_does_not_mutate_clip_plan(case,enabled,status,expected):
    selected=record(case);selected['status']=status
    canonical={'duration_seconds':5,'start_seconds':0,'end_seconds':5}
    task=NS(metadata_json=json.dumps({'optimize_h3_prompt':enabled,'h3_prompt_optimizer':selected,'requested_duration':5,'execution_contract':{'clip':canonical}}))
    duration,_=_apply_h3_execution_duration(task,5,NS(extension='{"max_clip_duration":15}'))
    metadata=json.loads(task.metadata_json)
    assert duration==expected and metadata['effective_duration']==expected
    assert metadata['requested_duration']==metadata['original_duration']==5
    assert metadata['execution_contract']['clip']==canonical
    assert metadata['duration_source']==('H3_PROMPT_OPTIMIZER' if enabled and status=='OPTIMIZED' else 'ORIGINAL')


def test_duration_reaches_existing_float_parameter_without_graph_change(case):
    builder=WorkflowBuilder()
    original={'132':{'class_type':'FloatConstant','inputs':{'value':5}},'138':{'class_type':'CR Prompt Text','inputs':{'text':'Raw'}},'126':{'class_type':'MathExpression|pysssss','inputs':{'a':['132',0],'expression':'frozen-frame-expression'}}}
    before=copy.deepcopy(original)
    metadata=opt.effective_execution_duration(5,record(case))
    graph=builder.build_video_workflow(case[2]['optimized_prompt'],json.dumps(original),{'duration_seconds_node_id':'132','prompt_node_id':'138'},duration_seconds=metadata['effective_duration'],seed=1)
    assert graph['132']['inputs']['value']==6
    assert graph['126']==before['126'] and list(graph)==list(before) and original==before


def test_temporal_retiming_uses_existing_projection_and_keeps_original(case):
    from app.services.clip_execution_compiler import project_temporal_anchor_positions
    manifest={'anchors':[{'anchor_id':'KF2','time_seconds':4.9,'image_url':'/a.png','local_path':'/a.png','source':{'id':'KF2'},'frame_position':119,'reachability':{'policy':'CANONICAL_MOTION_WINDOW_V1'}}]}
    before=copy.deepcopy(manifest)
    projected=opt.retime_temporal_manifest(manifest,record(case))
    expected=project_temporal_anchor_positions([{**manifest['anchors'][0],'time_seconds':5.2}],6)
    assert projected['anchors'][0]['frame_position']==expected[0]['frame_position']
    assert projected['anchors'][0]['original_time_seconds']==4.9 and manifest==before
    assert projected['anchors'][0]['initial_reachability']==before['anchors'][0]['reachability']


@pytest.mark.asyncio
async def test_regeneration_reuses_matching_prompt_timeline_duration_and_log(case,monkeypatch):
    raw,runtime,output=case
    monkeypatch.setattr(opt,'build_runtime_input',lambda *a:(runtime,[]))
    monkeypatch.setattr(opt,'resolve_prompt_template',lambda *a:NS(type=opt.TEMPLATE_TYPE,id='14',name='registered',template='system14'))
    monkeypatch.setattr(opt,'append_video_ai_call',lambda *a:None)
    chat=AsyncMock(return_value={'success':True,'content':json.dumps(output),'log_id':'same-log'})
    monkeypatch.setattr(opt,'LLMService',lambda:NS(chat_completion=chat))
    args=(Mock(),NS(id='n'),NS(index=1,chapter_id='c'),raw,'SINGLE_FRAME',{'clip_index':1,'planned_duration':5})
    prompt,first=await opt.optimize_h3_execution_prompt(*args)
    prompt_again,second=await opt.optimize_h3_execution_prompt(*args,reuse_record=first)
    assert second.get('reused_result') and chat.await_count==1
    assert prompt_again==prompt and first['effective_duration']==second['effective_duration']==6
    assert first['llm_log_id']==second['llm_log_id']=='same-log'
    changed=copy.deepcopy(first);changed['runtime_input']['immutable_authority']['subject_bindings']['<Subject 1>']='new'
    await opt.optimize_h3_execution_prompt(*args,reuse_record=changed)
    assert chat.await_count==2
    changed_context=copy.deepcopy(first)
    changed_context['runtime_input']['execution_context']={'execution_feedback':{'observed':'Wrong speaker mouth ownership'}}
    await opt.optimize_h3_execution_prompt(*args,reuse_record=changed_context)
    assert chat.await_count==3
    old_contract=copy.deepcopy(first);old_contract['version']='h3_execution_optimizer_unified_av_v2'
    await opt.optimize_h3_execution_prompt(*args,reuse_record=old_contract)
    assert chat.await_count==4


@pytest.mark.asyncio
async def test_real_worker_passes_effective_duration_to_generation(case,db_session,monkeypatch):
    from app.models.novel import Novel,Chapter
    from app.models.shot import Shot
    from app.models.task import Task
    from app.models.workflow import Workflow
    from app.services import shot_video_service as worker
    raw,runtime,output=case
    novel=Novel(title='execution-duration',aspect_ratio='16:9');db_session.add(novel);db_session.flush()
    chapter=Chapter(novel_id=novel.id,number=1,title='test');db_session.add(chapter);db_session.flush()
    shot=Shot(chapter_id=chapter.id,index=1,duration=5,characters='[]',props='[]',dialogues='[]',video_director_plan=json.dumps({'selected_mode':'SINGLE_FRAME'}));db_session.add(shot);db_session.flush()
    graph={'132':{'class_type':'FloatConstant','inputs':{'value':5}},'138':{'class_type':'CR Prompt Text','inputs':{'text':'raw'}}}
    workflow=Workflow(name='frozen',type='video',is_active=True,workflow_json=json.dumps(graph),node_mapping=json.dumps({'duration_seconds_node_id':'132','prompt_node_id':'138'}),extension='{"max_clip_duration":15}')
    db_session.add(workflow);db_session.flush()
    task=Task(type='shot_video',name='test',status='pending',novel_id=novel.id,chapter_id=chapter.id,shot_id=shot.id,workflow_id=workflow.id,metadata_json='{"optimize_h3_prompt":true}')
    db_session.add(task);db_session.commit()
    task_id,novel_id,chapter_id,workflow_id=task.id,novel.id,chapter.id,workflow.id
    monkeypatch.setattr(worker,'SessionLocal',lambda:db_session)
    monkeypatch.setattr(worker,'build_h3_video_prompt',AsyncMock(return_value=raw))
    monkeypatch.setattr(opt,'optimize_h3_execution_prompt',AsyncMock(return_value=(output['optimized_prompt'],record(case))))
    captured={}
    async def generate(**kwargs):
        captured.update(kwargs)
        captured['payload']=WorkflowBuilder().build_video_workflow(kwargs['prompt'],kwargs['workflow_json'],kwargs['node_mapping'],duration_seconds=kwargs['duration_seconds'],seed=1)
        return {'success':False,'message':'deliberate test stop before any remote submission'}
    monkeypatch.setattr(worker,'ComfyUIService',lambda:NS(generate_shot_video_with_workflow=generate))
    await worker.generate_shot_video_task(task_id,novel_id,chapter_id,1,workflow_id,'',optimize_h3_prompt=True)
    assert captured['duration_seconds']==6 and captured['payload']['132']['inputs']['value']==6
    assert captured['prompt']==output['optimized_prompt']


def test_legacy_raw_reuse_does_not_mistake_optimized_prompt_for_canonical():
    from app.services.shot_video_service import _get_reusable_video_prompt
    plan={'ai_calls':[{'step':'13','final_prompt':'canonical raw'},{'step':'14','final_prompt':'retimed optimized'}]}
    assert _get_reusable_video_prompt(plan)=='canonical raw'


def test_temporal_target_and_linked_arrival_remain_authoritative(case):
    raw,runtime,output=copy.deepcopy(case)
    raw+='\nTA1 — at 4.9s — Follow the same empty-hand visual target.\n'
    runtime['immutable_authority']['temporal_anchor_order']=[{'anchor_id':'TA1','source':{'id':'KF2'},'declaration_suffix':'— Follow the same empty-hand visual target.'}]
    runtime['initial_execution_timing']['temporal_anchors']=[{'anchor_id':'TA1','time_seconds':4.9}]
    output['optimized_prompt']=output['optimized_prompt'].replace('Hold the quiet ending naturally.','Follow the same empty-hand visual target. Hold the quiet ending naturally.')
    output['av_timeline']['anchors'].append({'id':'TA1','original_time':4.9,'optimized_time':5.2,'delta':0.3,'visual_state_changed':False,'reason':'Linked KF2 arrival','prompt_excerpt':'Follow the same empty-hand visual target.'})
    changed=(raw,runtime,output)
    assert audit(changed)['passed']
    output['optimized_prompt']=output['optimized_prompt'].replace('Follow the same empty-hand visual target.','Materialize a fabric prop.')
    assert 'anchor_prompt_rendering' in audit(changed)['blocking_findings']
    output['optimized_prompt']=output['optimized_prompt'].replace('Materialize a fabric prop.','Follow the same empty-hand visual target.').replace('TA1 — at 5.2s','TA1 — at 5.3s')
    output['av_timeline']['anchors'][-1].update(optimized_time=5.3,delta=0.4)
    assert 'linked_temporal_visual_arrival' in audit(changed)['blocking_findings']


@pytest.mark.asyncio
async def test_workflow_details_report_duration_contract(case,db_session):
    from app.api.tasks import get_task_workflow
    from app.models.task import Task
    from app.repositories import TaskRepository
    task=Task(type='shot_video',status='pending',name='preflight',metadata_json=json.dumps(opt.effective_execution_duration(5,record(case))),prompt_text=case[2]['optimized_prompt'])
    db_session.add(task);db_session.commit()
    response=await get_task_workflow(task.id,TaskRepository(db_session),db_session)
    assert response['data']['executionDuration']['original_duration']==5
    assert response['data']['executionDuration']['effective_duration']==6


@pytest.mark.parametrize('before,after,check',[
    ('summary:', 'old_summary:', 'h3_native_six_sections'),
    ('A 6-second', 'A 7-second', 'prompt_duration_matches_timeline'),
    ('[Chinese] 问？', '问？', 'native_dialogue_markup'),
    ('[Chinese] 答。', '[English] 答。', 'chinese_dialogue_language_marker'),
    ('<Subject 2> (S2)', '<Subject 2> (S1)', 'stable_speaker_ids'),
    ('<Subject 1> (S1)', '<Subject 2> (S2)', 'dialogue_ids_speakers_text_order'),
    ('A small lateral camera drift transfers emphasis from <Subject 1> to <Subject 2>, clearing a readable face and mouth while both keep their established positions.',
     'The two people nod.', 'speaker_switch_camera_evidence'),
    ('<Subject 1> closes his lips and listens. A small lateral camera drift transfers emphasis from <Subject 1> to <Subject 2>, clearing a readable face and mouth while both keep their established positions. All other visible characters listen naturally with relaxed closed lips and no speech-like articulation.',
     'A small lateral camera drift transfers emphasis from <Subject 1> to <Subject 2>, clearing a readable face and mouth while both keep their established positions.', 'speaker_switch_listener_settle'),
    ('<Subject 1> remains seated throughout the camera\'s gentle movement.',
     '<Subject 1> stands up and walks toward the camera.', 'no_acquisition_reblocking_<Subject 1>'),
])
def test_native_contract_rejects_regressions(case,before,after,check):
    output=copy.deepcopy(case[2]);assert before in output['optimized_prompt']
    output['optimized_prompt']=output['optimized_prompt'].replace(before,after)
    assert check in audit(case,output)['blocking_findings']


@pytest.mark.parametrize('leak',[
    'PHASE P00 — CAMERA — 0s–6s: camera plan',
    'PRIMARY: <Subject 1>', 'speaker: <Subject 1>',
    'start_time: 1s', 'end_time: 2s', 'exact_dialogue: 问？',
    'duration_source: H3_PROMPT_OPTIMIZER',
    'asset: bbfa698b-e38e-40db-8cc9-ae0ab381fc4f',
])
def test_internal_execution_data_never_leaks_to_final_prompt(case,leak):
    output=copy.deepcopy(case[2]);output['optimized_prompt']+='\n'+leak
    assert 'no_internal_execution_dsl' in audit(case,output)['blocking_findings']


def test_internal_phases_cannot_authorize_seated_character_walk(case):
    output=copy.deepcopy(case[2])
    output['av_timeline']['execution_phases'][1]['description']='A walks into the foreground to become readable.'
    assert 'no_acquisition_reblocking_<Subject 1>' in audit(case,output)['blocking_findings']


def test_blocking_detector_allows_authorized_canonical_movement(case):
    from app.services.h3_native_prompt import seated_subjects
    raw,runtime,_=case
    assert '<Subject 1>' in seated_subjects(raw,runtime['immutable_authority']['subject_bindings'])
    assert '<Subject 1>' not in seated_subjects(raw+'\n<Subject 1> stands up as the canonical story action.',runtime['immutable_authority']['subject_bindings'])


def test_stable_voice_ids_are_first_appearance_not_subject_numbers():
    from app.services.h3_native_prompt import speaker_bindings
    assert speaker_bindings([{'speaker':s} for s in ['<Subject 8>','<Subject 2>','<Subject 8>','<Subject 5>']])=={'<Subject 8>':'S1','<Subject 2>':'S2','<Subject 5>':'S3'}


@pytest.mark.asyncio
async def test_enabled_worker_stops_on_optimizer_preflight_failure(monkeypatch):
    from app.services.shot_video_service import _apply_h3_execution_optimizer
    task=NS(metadata_json='{"optimize_h3_prompt":true}')
    shot=NS(video_director_plan='{}',duration=5)
    optimize=AsyncMock(return_value=('raw',{'status':'FALLBACK','error':'bad native dialogue'}))
    monkeypatch.setattr(opt,'optimize_h3_execution_prompt',optimize)
    with pytest.raises(ValueError,match='停止视频生成'):
        await _apply_h3_execution_optimizer(Mock(),task,None,shot,'raw','SINGLE_FRAME',{'planned_duration':5})
    assert json.loads(task.metadata_json)['h3_prompt_optimizer']['generation_blocked'] is True


@pytest.mark.parametrize('time', [0, 2.0, 5.2, 6.0])
def test_anchor_arrival_point_is_legal_and_does_not_interrupt_coverage(case, time):
    output = copy.deepcopy(case[2])
    output['av_timeline']['execution_phases'].append({
        'id': 'arrival', 'type': 'ANCHOR_ARRIVAL', 'start': time, 'end': time,
        'description': 'The visual target is reached at this instant.'})
    assert audit(case, output)['passed']


@pytest.mark.parametrize('phase_type', ['CAMERA', 'ACTION', 'HANDOFF', 'DIALOGUE', 'FINAL_SETTLE'])
def test_ordinary_interval_cannot_be_zero_length(case, phase_type):
    output = copy.deepcopy(case[2])
    output['av_timeline']['execution_phases'].append({
        'id': 'bad', 'type': phase_type, 'start': 3, 'end': 3, 'description': 'Invalid duration.'})
    assert 'execution_phases_inside_budget' in audit(case, output)['blocking_findings']


@pytest.mark.parametrize('time', [-0.1, 6.1, float('nan'), float('inf')])
def test_anchor_point_must_be_finite_and_inside_budget(case, time):
    output = copy.deepcopy(case[2])
    output['av_timeline']['execution_phases'].append({
        'id': 'bad', 'type': 'ANCHOR_ARRIVAL', 'start': time, 'end': time, 'description': 'Invalid point.'})
    assert 'execution_phases_inside_budget' in audit(case, output)['blocking_findings']


def test_anchor_points_cannot_fill_or_extend_duration_coverage(case):
    output = copy.deepcopy(case[2])
    output['av_timeline']['execution_phases'] = [
        {'id': 'camera', 'type': 'CAMERA', 'start': 0, 'end': 2, 'description': 'First interval.'},
        {'id': 'point', 'type': 'ANCHOR_ARRIVAL', 'start': 3, 'end': 3, 'description': 'Uncovered instant.'},
        {'id': 'finish', 'type': 'FINAL_SETTLE', 'start': 4, 'end': 6, 'description': 'Last interval.'},
    ]
    result = audit(case, output)
    assert result['checks']['execution_phases_inside_budget']
    assert not result['checks']['execution_budget_explained']
    output['av_timeline']['execution_phases'] = [
        {'id': str(i), 'type': 'ANCHOR_ARRIVAL', 'start': i, 'end': i, 'description': 'Only points.'}
        for i in range(7)]
    assert not audit(case, output)['checks']['execution_budget_explained']


@pytest.fixture
def first_real_v4():
    from pathlib import Path
    return json.loads((Path(__file__).parent / 'fixtures/h3_native_v4_first_preflight.json').read_text())


def audit_first_real(data):
    return opt.check_authority(data['raw'], data['output'], **{
        'authority': data['runtime']['immutable_authority'],
        'initial_timing': data['runtime']['initial_execution_timing'],
        'limits': data['runtime']['duration_limits']})


def test_first_real_failure_is_not_bypassed_after_false_positive_fixes(first_real_v4):
    result = audit_first_real(first_real_v4)
    assert result['checks']['reference_authority_scope']
    assert result['checks']['execution_phases_inside_budget']
    assert result['checks']['execution_budget_explained']
    assert not result['checks']['speaker_switch_listener_settle']
    assert not result['checks']['speaker_switch_listener_scope']
    assert not result['passed']


def test_reference_identity_details_in_definitions_need_not_repeat_in_retention(first_real_v4):
    from app.services.h3_native_prompt import sections
    parts = sections(first_real_v4['output']['optimized_prompt'])
    assert 'face' in parts['subject_definitions'] and 'face' not in parts['retention_analysis']
    assert 'do not overwrite anchor staging or current costume' in parts['retention_analysis']
    assert audit_first_real(first_real_v4)['checks']['reference_authority_scope']


def test_reference_scope_cannot_be_satisfied_by_unrelated_action_prose(first_real_v4):
    from app.services.h3_native_prompt import sections
    p = first_real_v4['output']['optimized_prompt']
    definition = sections(p)['subject_definitions']
    first_real_v4['output']['optimized_prompt'] = p.replace(definition, definition.replace('face', 'appearance'))
    # detailed_description still contains face, but cannot supply reference authority.
    assert not audit_first_real(first_real_v4)['checks']['reference_authority_scope']


@pytest.mark.parametrize('listener_clause,passed', [
    ('All other visible characters listen naturally with relaxed closed lips and no speech-like articulation.', True),
    ('<Subject 1>, <Subject 3>, and <Subject 4> listen naturally with relaxed closed lips and no speech-like articulation.', True),
    ('<Subject 1> listens naturally with relaxed closed lips and no speech-like articulation.', False),
    ('All other visible characters listen naturally with relaxed closed lips.', False),
    ('All other visible characters react naturally without speech-like articulation.', False),
    ('The outgoing speaker closes his mouth. Others stand still.', False),
])
def test_every_switch_must_explicitly_cover_all_visible_listeners(case, listener_clause, passed):
    output = copy.deepcopy(case[2])
    raw, runtime, _ = copy.deepcopy(case)
    runtime['immutable_authority']['subject_bindings'].update({'<Subject 3>': 'C', '<Subject 4>': 'D'})
    old = 'All other visible characters listen naturally with relaxed closed lips and no speech-like articulation.'
    output['optimized_prompt'] = output['optimized_prompt'].replace(old, listener_clause)
    result = opt.check_authority(raw, output, runtime['immutable_authority'], runtime['initial_execution_timing'], runtime['duration_limits'])
    assert result['checks']['speaker_switch_listener_scope'] is passed


def test_listener_state_before_previous_dialogue_cannot_cover_next_switch(case):
    output = copy.deepcopy(case[2])
    sentence = 'All other visible characters listen naturally with relaxed closed lips and no speech-like articulation.'
    output['optimized_prompt'] = output['optimized_prompt'].replace(sentence, '').replace(
        '<Subject 1> (S1) asks,', sentence + '\n<Subject 1> (S1) asks,')
    assert not audit(case, output)['checks']['speaker_switch_listener_scope']


@pytest.mark.parametrize('field', ['release', 'acquisition', 'listeners', 'dialogue_entry'])
def test_handoff_trace_must_quote_current_local_prose(case, field):
    output = copy.deepcopy(case[2])
    evidence = output['av_timeline']['handoffs'][0]['prompt_evidence']
    evidence[field] = 'Invented evidence not present in the prompt.'
    assert not audit(case, output)['checks']['speaker_switch_camera_evidence']


def test_camera_words_in_global_prose_do_not_prove_a_local_handoff(case):
    output = copy.deepcopy(case[2])
    excerpt = output['av_timeline']['handoffs'][0]['prompt_evidence']['acquisition']
    output['optimized_prompt'] = output['optimized_prompt'].replace(excerpt, '').replace(
        'summary:\n', 'summary:\n' + excerpt + '\n')
    assert not audit(case, output)['checks']['speaker_switch_camera_evidence']


@pytest.mark.parametrize('change', ['wrong_subject', 'wrong_pair', 'entry_before_ready', 'release_after_ready'])
def test_camera_trace_binds_participants_and_local_order(case, change):
    output = copy.deepcopy(case[2])
    handoff = output['av_timeline']['handoffs'][0]
    evidence = handoff['prompt_evidence']
    if change == 'wrong_subject':
        original = evidence['acquisition']
        evidence['acquisition'] = original.replace('<Subject 2>', '<Subject 8>')
        output['optimized_prompt'] = output['optimized_prompt'].replace(original, evidence['acquisition'])
    elif change == 'wrong_pair':
        handoff['from'] = 'D9'
    elif change == 'entry_before_ready':
        output['optimized_prompt'] = output['optimized_prompt'].replace(evidence['dialogue_entry'], '').replace(
            evidence['release'], evidence['dialogue_entry'] + evidence['release'])
    else:
        output['optimized_prompt'] = output['optimized_prompt'].replace(evidence['release'], '').replace(
            evidence['acquisition'], evidence['acquisition'] + ' ' + evidence['release'])
    assert not audit(case, output)['checks']['speaker_switch_camera_evidence']


@pytest.mark.parametrize('action', [
    'A restrained pan carries the view from <Subject 1> onto <Subject 2>, ending with the face and lips legible at the established standing place.',
    'The frame eases off <Subject 1> and settles around <Subject 2>; the face and lips can now be followed without either person changing position.',
    'Cut from <Subject 1> to a readable view of <Subject 2> at the established standing place, preserving both floor positions and their eyelines.',
])
def test_equivalent_camera_prose_needs_no_action_keyword_whitelist(case, action):
    output = copy.deepcopy(case[2])
    evidence = output['av_timeline']['handoffs'][0]['prompt_evidence']
    output['optimized_prompt'] = output['optimized_prompt'].replace(evidence['acquisition'], action)
    evidence['acquisition'] = action
    if action.startswith('Cut from'):
        output['optimized_prompt'] = output['optimized_prompt'].replace('continuous ensemble shot', 'speaker-motivated edited sequence')
        handoff = output['av_timeline']['handoffs'][0]
        handoff['camera_strategy'] = action
        output['av_timeline']['execution_phases'][1]['description'] = action
    assert audit(case, output)['passed']


def test_edited_prose_does_not_warn_that_upstream_continuous_wording_is_missing(case):
    output = copy.deepcopy(case[2])
    action = ('Cut from <Subject 1> to a readable view of <Subject 2> at the same standing place, '
              'preserving both floor positions and their eyelines.')
    handoff = output['av_timeline']['handoffs'][0]
    evidence = handoff['prompt_evidence']
    output['optimized_prompt'] = output['optimized_prompt'].replace(evidence['acquisition'], action).replace(
        'continuous ensemble shot', 'speaker-motivated edited sequence')
    evidence['acquisition'] = handoff['camera_strategy'] = action
    output['av_timeline']['execution_phases'][1]['description'] = action
    raw = case[0] + '\nCONTINUOUS_TAKE: upstream initial camera preference.'
    result = audit((raw, case[1], output))
    assert result['passed'], result['blocking_findings']
    assert not any(w['code'] == 'CONTINUOUS_CAMERA_WORDING_WEAK' for w in result['warnings'])
    # Editing freedom does not relax per-line source IDs or listener evidence.
    output['optimized_prompt'] = output['optimized_prompt'].replace('<Subject 2> (S2)', '<Subject 2>')
    assert not audit((raw, case[1], output))['checks']['stable_speaker_ids']


@pytest.mark.parametrize('prior_view', [True, False])
def test_maintained_view_requires_immediately_previous_evidence(case, prior_view):
    output = copy.deepcopy(case[2])
    handoff = output['av_timeline']['handoffs'][0]
    evidence = handoff['prompt_evidence']
    handoff['camera_handoff_required'] = False
    view = '<Subject 2> shares the readable two-shot with face and mouth unobstructed.'
    if prior_view:
        output['optimized_prompt'] = output['optimized_prompt'].replace('<Subject 1> (S1) asks,', view + '\n<Subject 1> (S1) asks,')
    else:
        # Current readiness cannot self-certify an already acquired prior view.
        output['optimized_prompt'] = output['optimized_prompt'].replace(evidence['release'], view + '\n' + evidence['release'])
    evidence['existing_view_excerpt'] = view
    maintained = 'The camera holds the already readable view of <Subject 2> as attention shifts to the reply, with both floor positions preserved.'
    output['optimized_prompt'] = output['optimized_prompt'].replace(evidence['acquisition'], maintained)
    evidence['acquisition'] = maintained
    assert audit(case, output)['checks']['speaker_switch_camera_evidence'] is prior_view


def test_local_trace_does_not_claim_to_certify_camera_semantics(case):
    output = copy.deepcopy(case[2])
    evidence = output['av_timeline']['handoffs'][0]['prompt_evidence']
    target_only = '<Subject 1> and <Subject 2> have readable faces and mouths.'
    output['optimized_prompt'] = output['optimized_prompt'].replace(evidence['acquisition'], target_only)
    evidence['acquisition'] = target_only
    # Provenance can pass while semantic preflight must reject missing transition.
    assert audit(case, output)['checks']['speaker_switch_camera_evidence']


def test_listener_settling_can_accompany_camera_action(case):
    output = copy.deepcopy(case[2])
    evidence = output['av_timeline']['handoffs'][0]['prompt_evidence']
    acquisition, listeners = evidence['acquisition'], evidence['listeners']
    output['optimized_prompt'] = output['optimized_prompt'].replace(
        acquisition + ' ' + listeners, listeners + ' ' + acquisition)
    assert audit(case, output)['passed']


def test_camera_can_start_before_release_and_finish_after_it(case):
    output = copy.deepcopy(case[2])
    evidence = output['av_timeline']['handoffs'][0]['prompt_evidence']
    concurrent = ('The camera begins a shallow arc from <Subject 1> toward <Subject 2>. '
                  '<Subject 1> closes his lips and listens. '
                  'The view then settles with the incoming face and mouth readable at the unchanged position.')
    output['optimized_prompt'] = output['optimized_prompt'].replace(
        evidence['release'] + ' ' + evidence['acquisition'], concurrent)
    evidence['acquisition'] = concurrent
    assert audit(case, output)['passed']


@pytest.mark.parametrize('duration', [15.375, 18.5, 20.0])
def test_optimizer_and_worker_accept_extended_execution_budget(case, duration):
    output=case[2]
    output['optimized_prompt']=output['optimized_prompt'].replace('A 6-second', f'A {duration:g}-second')
    output['av_timeline'].update(optimized_duration=duration, duration_delta=duration-5)
    output['av_timeline']['execution_phases'][-1]['end']=duration
    checked=audit(case)
    assert checked['passed'], checked['blocking_findings']
    task=NS(metadata_json=json.dumps({'capability':'GENERATE','optimize_h3_prompt':True,'h3_prompt_optimizer':record(case)}))
    assert _apply_h3_execution_duration(task,5,NS(extension='{}'))[0]==duration
