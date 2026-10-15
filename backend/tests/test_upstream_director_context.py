"""Real saved Shot13 projections; no live database, LLM, or media service."""
import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.api import shots as api
from app.constants.prompt_template import TRANSITION_INPUT_V1, TRANSITION_INPUT_V2, TRANSITION_V1_NAME, TRANSITION_V2_NAME
from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.repositories.prompt_template import PromptTemplateRepository
from app.services.director_context import effective_visual_states, transition_input_contract
from app.services.clip_planner import build_clip_planner_input
from app.services.prompt_template_service import PromptTemplateService
from app.services import video_director_ai as builder, h3_phase_b_pipeline as pipeline, h3_single_stage_experiment as compiler
from app.services.shot_video_service import _semantic_clip_prompt_context

ROOT = Path(__file__).parent
TEMPLATES = ROOT.parent / 'prompt_templates'

@pytest.fixture(autouse=True)
def no_external_services(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Unexpected real LLM/ComfyUI call')
    from app.services.llm_service import LLMService
    from app.services.comfyui.client import ComfyUIClient
    monkeypatch.setattr(LLMService, 'chat_completion', forbidden)
    for method in ('queue_prompt', 'upload_image', 'upload_video'):
        monkeypatch.setattr(ComfyUIClient, method, forbidden)

@pytest.fixture
def real_case():
    data = json.loads((ROOT / 'fixtures/shot13_upstream_context.json').read_text())
    shot = SimpleNamespace(**data['shot'], video_director_plan=json.dumps(data['saved_plan'], ensure_ascii=False))
    return data, shot

def payload(shot, plan, segment, contract=TRANSITION_INPUT_V2):
    kwargs = {'input_contract': contract}
    if contract == TRANSITION_INPUT_V2:
        kwargs['dialogue_timeline_source'] = plan['dialogue_timeline_source']
    return json.loads(api._build_keyframe_transition_user_content(
        shot, *plan['keyframes'][segment-1:segment+1], segment, **kwargs).split('\n\n', 1)[1])

@pytest.mark.parametrize('empty', [None, '', '  '])
def test_start_resolution_read_only(real_case, empty):
    data, shot = real_case
    raw = deepcopy(data['raw_08']['keyframes']); raw[0]['description'] = empty
    before = deepcopy(raw)
    resolved, evidence = effective_visual_states(raw, shot.description)
    assert raw == before and resolved[0]['description'] == shot.description
    assert resolved[1:] == raw[1:]
    assert evidence == [{'keyframe_index': 1, 'status': 'RESOLVED', 'source': 'Shot.description', 'reason': 'START_REFERENCE'}]
    resolved[0]['index'] = 999
    assert raw == before

def test_nonempty_nonstart_unknown_source(real_case):
    data, shot = real_case
    raw = deepcopy(data['saved_plan']['keyframes'])
    raw[0]['description'] = 'Explicit historical START'; raw[1]['description'] = None
    assert effective_visual_states(raw, shot.description) == (raw, [])
    raw[0]['description'] = None
    effective, evidence = effective_visual_states(raw, None)
    assert effective == raw and evidence[0]['status'] == 'UNKNOWN'
    shot.description = None
    p = payload(shot, {**data['saved_plan'], 'keyframes': raw}, 1)
    assert p['from_keyframe']['description'] == ''
    assert p['start_visual_resolution'][0]['reason'] == 'START_VISUAL_SOURCE_MISSING'

@pytest.mark.parametrize('segment,overlap,adjacent', [
    (1, ['D1'], ['D2']), (3, ['D6', 'D7', 'D8'], ['D5', 'D9']),
    (5, ['D9', 'D10', 'D11'], ['D8']), (6, ['D11'], ['D10']),
])
def test_real_transition_causal_projection(real_case, segment, overlap, adjacent):
    data, shot = real_case; original = deepcopy(data)
    p = payload(shot, data['saved_plan'], segment)
    assert p['input_contract'] == TRANSITION_INPUT_V2
    assert p['causal_context']['shot_video_description'] == shot.video_description
    ctx = p['causal_context']['segment_dialogue_state']
    assert ctx['time_domain'] == 'SHOT_SECONDS'
    assert ctx['overlapping_dialogue_ids'] == overlap and ctx['adjacent_dialogue_ids'] == adjacent
    assert ctx['start_time'] == p['from_keyframe']['time_seconds']
    assert ctx['end_time'] == p['to_keyframe']['time_seconds']
    assert ctx['dialogue_timeline_source'] == [d for d in data['saved_plan']['dialogue_timeline_source'] if d['id'] in set(overlap + adjacent)]
    if segment == 1:
        assert p['from_keyframe']['description'] == shot.description
        assert '入口内' in p['from_keyframe']['description']
        assert '走到桌前' in p['causal_context']['shot_video_description']
    if segment in (5, 6):
        assert '沉默退出书房' in p['causal_context']['shot_video_description']
        assert '独处' in p['causal_context']['shot_video_description']
    assert data == original and json.loads(shot.video_director_plan) == data['saved_plan']

def test_no_overlap_and_no_timing_estimator(real_case, monkeypatch):
    data, shot = real_case
    monkeypatch.setattr(api, 'resolve_canonical_dialogue_timeline', lambda *a, **kw: pytest.fail('No estimation'))
    ctx = api._build_segment_dialogue_state(shot, {'time_seconds': 4.25}, {'time_seconds': 4.45}, data['saved_plan']['dialogue_timeline_source'])
    assert ctx['overlapping_dialogue_ids'] == [] and ctx['adjacent_dialogue_ids'] == ['D1', 'D2']
    with pytest.raises(ValueError, match='TIMELINE_MISSING'):
        api._build_keyframe_transition_user_content(shot, *data['saved_plan']['keyframes'][:2], 1, input_contract=TRANSITION_INPUT_V2)
    with pytest.raises(ValueError, match='CONTRACT_MISMATCH'):
        api._build_keyframe_transition_user_content(shot, *data['saved_plan']['keyframes'][:2], 1,
            input_contract=TRANSITION_INPUT_V1, dialogue_timeline_source=[])

def test_clip_planner_effective_start(real_case):
    data, shot = real_case; before = shot.video_director_plan
    result = build_clip_planner_input(shot, [], resolved_dialogue_timeline=data['saved_plan']['dialogue_timeline_source'])
    assert result['visual_state_candidates'][0]['description'] == shot.description
    assert [s['description'] for s in result['visual_state_candidates'][1:]] == [s['description'] for s in data['saved_plan']['keyframes'][1:]]
    assert result['transition_context'][0]['transition_description'] == data['saved_plan']['transitions'][0]['transition_description']
    assert shot.video_director_plan == before

def test_legacy_h3_builder_effective_start(real_case, monkeypatch, db_session):
    data, shot = real_case; plan = data['saved_plan']; before = deepcopy(plan)
    context = _semantic_clip_prompt_context(plan, {'clip_index': 1})
    monkeypatch.setattr(builder, 'get_visual_prop_names', lambda *a: json.loads(shot.props))
    result = asyncio.run(builder.build_h3_video_prompt(
        db=db_session, novel=SimpleNamespace(id='offline'), shot=shot, selected_mode='MULTI_KEYFRAME',
        clip=context['clip'], workflow_capability={}, workflow_type='multi_reference_video', workflow_name='frozen',
        start_image_url=None, keyframes=context['keyframes'], transitions=context['transitions'],
        clip_dialogues=context['clip_dialogues'], reference_images=[], video_reference_manifest={'references': []},
        input_only=True, resolved_dialogue_timeline=plan['dialogue_timeline_source']))
    assert result['visual_controls'][0]['description'] == shot.description
    assert result['start_visual_resolution'][0]['status'] == 'RESOLVED'
    assert [s['description'] for s in result['visual_controls'][1:]] == [s['description'] for s in plan['keyframes'][1:3]]
    assert plan == before and json.loads(shot.video_director_plan) == plan

def test_phase_b_consistent_runtime_views_and_strict_check(db_session):
    from test_h3_phase_b_pipeline import make_case
    snap, args, _ = make_case(db_session, 'shot12_c1_generate')
    shot=args['shot']; plan=json.loads(shot.video_director_plan); original=deepcopy(plan)
    shot.description='Scene: throne hall. Emperor and steward retain their established positions.'
    current=deepcopy(args['builder_input'])
    current['visual_controls'], _=effective_visual_states(current['visual_controls'], shot.description)
    kw=dict(plan=plan,builder_input=current,manifest=args['manifest'],workflow=args['workflow'],
        previous_path=args['previous_path'],execution_contract=args['execution_contract'],shot_description=shot.description)
    result=pipeline.runtime_snapshot(**kw)
    assert result['canonical_plan']['keyframes'][0]['description']==current['visual_controls'][0]['description']==shot.description
    assert result['source']['start_visual_resolution'][0]['status']=='RESOLVED'
    assert compiler.prepare_multi_keyframe_phase_b(result,runtime=True)['status']=='PREPARED'
    assert plan==original
    current['visual_controls'][0]['description']='Tampered authority'
    failed=compiler.prepare_multi_keyframe_phase_b(pipeline.runtime_snapshot(**kw),runtime=True)
    assert failed['status']=='NOT_COVERED' and 'SAVED_STATES_MISMATCH' in str(failed['reasons'])
    assert compiler.prepare_multi_keyframe_phase_b(snap)['status']=='PREPARED'

def test_registration_preserves_v1_and_user_versions(db_session):
    old=PromptTemplate(name=TRANSITION_V1_NAME,type='keyframe_transition',is_system=True,template='Historical system body',description='Historical description',is_active=True)
    custom=PromptTemplate(name='My original copy',type='keyframe_transition',is_system=False,template='User-owned body',description='User description',is_active=True)
    db_session.add_all([old,custom]);db_session.commit()
    before={t.id:(t.template,t.description,t.updated_at) for t in (old,custom)}
    service=PromptTemplateService(db_session);service.init_system_templates();service.init_system_templates()
    repo=PromptTemplateRepository(db_session);current=repo.resolve_for_type(None,'keyframe_transition')
    assert current.name==TRANSITION_V2_NAME
    assert current.template==(TEMPLATES/'10_NovelFlow_KeyframeTransition_Planner_V2.txt').read_text()
    assert transition_input_contract(current)==TRANSITION_INPUT_V2
    for t in (old,custom):
        assert (t.template,t.description,t.updated_at)==before[t.id]
        assert repo.resolve_for_type(t.id,'keyframe_transition').id==t.id
        assert transition_input_contract(t)==TRANSITION_INPUT_V1
    copied=service.copy_template(current.id)
    assert not copied.is_system and transition_input_contract(copied)==TRANSITION_INPUT_V2
    original_copy = copied.template
    with pytest.raises(ValueError, match='CONTRACT_MISMATCH'):
        service.update_template(copied.id, template='\n'.join(
            line for line in copied.template.splitlines() if not line.startswith('INPUT_CONTRACT:')))
    assert copied.template == original_copy
    from app.api.prompt_templates import update_prompt_template
    from app.schemas.prompt_template import PromptTemplateUpdate
    with pytest.raises(HTTPException) as error:
        update_prompt_template(copied.id, PromptTemplateUpdate(template='removed marker'), service)
    assert error.value.status_code == 409 and 'CONTRACT_MISMATCH' in error.value.detail
    service.update_template(copied.id,template=copied.template+'\nUser addition');service.init_system_templates()
    assert copied.template.endswith('User addition')
    assert repo.resolve_for_type(copied.id,'keyframe_transition').id==copied.id
    assert db_session.query(PromptTemplate).filter_by(name=TRANSITION_V2_NAME,is_system=True).count()==1
    current.is_active=False;db_session.flush()
    assert repo.resolve_for_type(None,'keyframe_transition').id==old.id

@pytest.mark.parametrize('body', ['INPUT_CONTRACT: UNKNOWN','INPUT_CONTRACT: KEYFRAME_TRANSITION_CAUSAL_V2\nINPUT_CONTRACT: KEYFRAME_TRANSITION_VISUAL_V1'])
def test_mismatched_contract_rejected_before_llm(db_session, body):
    row=PromptTemplate(name='custom marked contract',type='keyframe_transition',template=body,is_active=True)
    db_session.add(row);db_session.flush()
    novel=Novel(title='offline',keyframe_transition_prompt_template_id=row.id)
    with pytest.raises(HTTPException,match='CONTRACT_MISMATCH'):
        api._get_keyframe_transition_template(novel,PromptTemplateRepository(db_session))

def test_v2_named_missing_marker_not_silently_v1():
    with pytest.raises(ValueError,match='CONTRACT_MISMATCH'):
        transition_input_contract(SimpleNamespace(name=TRANSITION_V2_NAME,template='marker removed'))

@pytest.mark.parametrize('contract',[TRANSITION_INPUT_V1,TRANSITION_INPUT_V2])
def test_six_real_edges_mock_calls_and_output_unchanged(real_case, monkeypatch, contract):
    data,shot=real_case;before=shot.video_director_plan
    filename='10_NovelFlow_KeyframeTransition_Planner_'+('V1' if contract==TRANSITION_INPUT_V1 else 'V2')+'.txt'
    template=SimpleNamespace(id='offline',name='V1 user' if contract==TRANSITION_INPUT_V1 else TRANSITION_V2_NAME,template=(TEMPLATES/filename).read_text())
    repo=SimpleNamespace(resolve_for_type=lambda *a:template);calls=[]
    class FakeLLM:
        async def chat_completion(self,**kw):
            calls.append(kw)
            return {'success':True,'content':json.dumps(data['saved_plan']['transitions'][len(calls)-1],ensure_ascii=False)}
    monkeypatch.setattr(api,'get_style',lambda *a:('',None));records=[]
    transitions=asyncio.run(api._plan_keyframe_transitions(
        SimpleNamespace(commit=lambda:pytest.fail('No production write')),
        SimpleNamespace(id='novel',keyframe_transition_prompt_template_id=None),SimpleNamespace(id='chapter'),
        shot,deepcopy(data['saved_plan']['keyframes']),repo,FakeLLM(),call_records=records))
    assert len(calls)==len(transitions)==len(records)==6
    assert transitions==data['saved_plan']['transitions']
    for call,record in zip(calls,records):
        p=json.loads(call['user_content'].split('\n\n',1)[1])
        assert ('causal_context' in p)==(contract==TRANSITION_INPUT_V2)
        assert record['parsed_result']['input_contract']==contract
        assert call['system_prompt']==template.template
    assert shot.video_director_plan==before
    assert all(set(t)=={'segment_index','from_keyframe_index','to_keyframe_index','start_time','end_time','transition_description'} for t in transitions)

def test_output_schema_and_v1_template_preserved():
    v1=(TEMPLATES/'10_NovelFlow_KeyframeTransition_Planner_V1.txt').read_text()
    v2=(TEMPLATES/'10_NovelFlow_KeyframeTransition_Planner_V2.txt').read_text()
    assert v1.split('【输出格式】',1)[1]==v2.split('【输出格式】',1)[1]
    assert '输入不包含 dialogue timeline' in v1 and '输入不包含 dialogue timeline' not in v2
    assert '邻近 Dialogue 只用于理解前置原因和后续边界' in v2
    assert '不得提前下一 Transition' in v2

@pytest.mark.parametrize('timeline', [None, []])
def test_v2_missing_or_inconsistent_official_timeline_stops_without_llm(real_case, timeline):
    data, shot = real_case
    plan = deepcopy(data['saved_plan'])
    if timeline is None:
        plan.pop('dialogue_timeline_source')
    else:
        plan['dialogue_timeline_source'] = timeline
    shot.video_director_plan = json.dumps(plan)
    template = SimpleNamespace(id='offline', name=TRANSITION_V2_NAME,
        template=(TEMPLATES/'10_NovelFlow_KeyframeTransition_Planner_V2.txt').read_text())
    repo = SimpleNamespace(resolve_for_type=lambda *a: template)
    class NoLLM:
        async def chat_completion(self, **kw):
            pytest.fail('Invalid official timeline must not reach LLM')
    with pytest.raises(HTTPException, match='TRANSITION_CANONICAL_TIMELINE_'):
        asyncio.run(api._plan_keyframe_transitions(SimpleNamespace(),
            SimpleNamespace(keyframe_transition_prompt_template_id=None), SimpleNamespace(),
            shot, plan['keyframes'], repo, NoLLM(), call_records=[]))
