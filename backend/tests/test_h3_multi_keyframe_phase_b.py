"""Real upstream assets + synthetic Director decisions. No network, #14 or DB."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.services import h3_single_stage_experiment as stage
from app.services.h3_native_prompt import SECTIONS, sections, dialogue_events
from app.services.clip_execution_compiler import project_temporal_anchor_positions

ROOT = Path(__file__).parent / 'fixtures/h3_multi_keyframe_phase_b'
NAMES = ['shot12_c1_generate', 'shot3_c6_extend', 'shot5_c2_temporal_extend']

def saved(name, suffix=''):
    return json.loads((ROOT / (name + suffix + '.json')).read_text())

@pytest.fixture(autouse=True)
def no_external_stages(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Forbidden external stage or client')
    from app.services import h3_execution_optimizer, h3_preflight_repair
    from app.services.llm_service import LLMService
    from app.services.comfyui.client import ComfyUIClient
    monkeypatch.setattr(stage, 'prepare_multi_keyframe_phase_a', forbidden)
    monkeypatch.setattr(h3_execution_optimizer, 'check_authority', forbidden)
    monkeypatch.setattr(h3_execution_optimizer, 'optimize_h3_execution_prompt', forbidden)
    monkeypatch.setattr(h3_preflight_repair, 'repair_output', forbidden)
    monkeypatch.setattr(LLMService, 'chat_completion', forbidden)
    monkeypatch.setattr(ComfyUIClient, 'queue_prompt', forbidden)

@pytest.fixture(scope='module')
def prepared():
    result = {}
    for name in NAMES:
        source = saved(name); before = deepcopy(source)
        result[name] = stage.prepare_multi_keyframe_phase_b(source)
        assert result[name]['status'] == 'PREPARED', result[name]
        assert source == before
    return result

@pytest.mark.parametrize('name,ordinary,temporal,previous,states', [
    (NAMES[0],9,0,0,5), (NAMES[1],9,0,5,4), (NAMES[2],5,1,5,3)])
def test_upstream_only_real_previews(prepared,name,ordinary,temporal,previous,states):
    p = prepared[name]; wire = json.dumps(p['llm_input'], ensure_ascii=False)
    for key in ['frozen_execution','optimized_duration','optimized_start','optimized_end',
                'optimized_time','execution_phases','handoffs','authority_echo','frozen_record']:
        assert '"'+key+'"' not in wire
    assert len(p['reference_manifest']['references']) == ordinary
    assert len(p['images']) == ordinary+temporal+previous
    assert len(p['llm_input']['previous_av']['preview_frames']) == previous
    assert len(p['llm_input']['canonical']['owned_visual_states']) == states
    assert all(i['url'].startswith('data:image/') for i in p['images'])
    assert '"prompt_text"' not in wire
    assert not p['submission_authorized'] and not p['production_preflight_passed']

@pytest.mark.parametrize('name',NAMES)
def test_new_response_compiles_without_mutation(prepared,name):
    p=prepared[name];response=saved(name,'_mock_response');old_p,old_r=deepcopy(p),deepcopy(response)
    result=stage.compile_multi_keyframe_phase_b(p,response)
    assert result['status']=='CANDIDATE_FOR_REVIEW',result
    assert p==old_p and response==old_r
    assert result['execution_decisions']['decision_owner']=='NEW_13_PHASE_B'
    timeline=result['execution_decisions']['timing']
    assert timeline['optimized_duration']==response['optimized_duration']
    for e,r,c in zip(timeline['dialogue_events'],response['dialogue_events'],p['canonical']):
        assert e['optimized_start']==r['start']
        assert e['optimized_end']==pytest.approx(r['start']+c['duration'])
        assert e['speaker']==c['speaker']
        assert e['delta']==pytest.approx(e['optimized_start']-e['original_start'])
        assert e['original_time_base']=='CLIP_STORY_SECONDS'
        assert e['optimized_time_base']=='GENERATION_LOCAL_SECONDS'
    assert [g['seconds'] for g in result['execution_decisions']['gaps']]==pytest.approx([
        b['optimized_start']-a['optimized_end'] for a,b in zip(timeline['dialogue_events'],timeline['dialogue_events'][1:])])
    assert list(sections(result['prompt']))==list(SECTIONS)
    assert all(result['review']['structure'].values())
    assert all(result['review']['structured_authority'].values())
    assert result['picture_audit']['passed']
    assert [(e['speaker'],e['exact_dialogue']) for e in dialogue_events(result['prompt'])]==[(e['speaker'],e['exact_dialogue']) for e in p['canonical']]
    detail=sections(result['prompt'])['detailed_description']
    for i,event in reversed(list(enumerate(dialogue_events(result['prompt']),1))):
        detail=detail[:event['span_start']]+'[[SPEECH_%d]]'%i+detail[event['span_end']:]
    assert detail==response['detailed_description']
    assert sections(result['prompt'])['overall_soundscape']==response['overall_soundscape']
    assert result['director_semantics']['status']=='REVIEW_REQUIRED'
    assert not result['submission_authorized'] and not result['production_preflight_passed']

@pytest.mark.parametrize('name',NAMES[1:])
def test_overlap_once_and_source_coordinate(prepared,name):
    p=prepared[name];assert p['continuation']['overlap_seconds']==1.625
    frames=p['llm_input']['previous_av']['preview_frames']
    assert frames[0]['generation_local_time_seconds']==0 and frames[0]['source_video_time_seconds']>0
    assert frames[0]['time_base']=='PREVIOUS_AV_SOURCE_SECONDS'
    r=stage.compile_multi_keyframe_phase_b(p,saved(name,'_mock_response'))
    assert all(r['continuation_checks'].values())
    assert r['execution_decisions']['timing']['dialogue_events'][0]['optimized_start']==saved(name,'_mock_response')['dialogue_events'][0]['start']
    assert any('0–1.625s' in line for line in r['review']['compiler_owned_execution_notes'])

def test_drop_projection_preserves_canonical(prepared):
    p=prepared[NAMES[1]];states=deepcopy(p['llm_input']['canonical'])
    r=stage.compile_multi_keyframe_phase_b(p,saved(NAMES[1],'_mock_response'))
    assert p['llm_input']['canonical']==states
    assert [s['index'] for s in states['owned_visual_states']]==[9,10,11,12]
    assert {t['segment_index'] for t in states['transitions']}=={8,9,10,11,12}
    assert states['transitions'][-1]['projection_mode']=='CROSS_CLIP_OPENING'
    assert states['transitions'][0]['projection_mode']=='CROSS_CLIP_CONTINUATION'
    refs=r['reference_manifest']['references']
    assert [x['source_slot'] for x in refs]==[1,4,5,6,7,8,9]
    assert [x['slot'] for x in refs]==list(range(1,8))
    for x in refs:assert x['local_path']==p['reference_manifest']['references'][x['source_slot']-1]['local_path']
    assert [x['anchor_id'] for x in r['reference_manifest']['excluded_references']]==['KF10','KF11']
    assert 'KF10, KF11: no reference-image arrival constraint' in r['prompt']
    assert r['execution_decisions']['anchor_decisions'][0]['optimized_time']!=1.85
    assert r['execution_decisions']['anchor_decisions'][-1]['optimized_time']!=9.7

def test_temporal_alias_and_frame_formula(prepared):
    p=prepared[NAMES[2]];r=stage.compile_multi_keyframe_phase_b(p,saved(NAMES[2],'_mock_response'))
    choices={a['id']:a for a in r['execution_decisions']['anchor_decisions']}
    assert choices['KF6']['optimized_time']==choices['clip-2-KF6']['optimized_time']
    assert r['temporal_manifest']['anchors']==project_temporal_anchor_positions(
        [{**p['temporal_anchors'][0],'time_seconds':choices['KF6']['optimized_time']}],r['execution_decisions']['timing']['optimized_duration'])
    assert len(r['picture_mapping'])==5
    assert not any(x['kind']=='TEMPORAL_ANCHOR' for x in r['picture_mapping'])

def test_temporal_alias_drop_together(prepared):
    response=saved(NAMES[2],'_mock_response')
    for a in response['anchors']:
        if a['id'] in ['KF6','clip-2-KF6']:a.update(decision='DROP',optimized_time=None,arrival_relation=None)
    r=stage.compile_multi_keyframe_phase_b(prepared[NAMES[2]],response)
    assert r['status']=='CANDIDATE_FOR_REVIEW',r
    assert r['temporal_manifest']['anchors']==[] and len(r['picture_mapping'])==5
    assert len(r['temporal_manifest']['excluded_anchors'])==1

@pytest.mark.parametrize('mutation',['duration_nan','duration_max','dialogue_reorder','dialogue_speaker',
 'negative_start','overlap','speech_end','prefix','anchor_missing','unknown_anchor','keep_retime',
 'drop_arrival','anchor_nan','relation','anchor_prefix','anchor_order','prose_missing','speech_text'])
def test_bad_output_rejected(prepared,mutation):
    r=saved(NAMES[1],'_mock_response')
    if mutation=='duration_nan':r['optimized_duration']=float('nan')
    elif mutation=='duration_max':r['optimized_duration']=21
    elif mutation=='dialogue_reorder':r['dialogue_events'].reverse()
    elif mutation=='dialogue_speaker':r['dialogue_events'][0]['speaker']='<Subject 1>'
    elif mutation=='negative_start':r['dialogue_events'][0]['start']=-1
    elif mutation=='overlap':r['dialogue_events'][1]['start']=2
    elif mutation=='speech_end':r['dialogue_events'][-1]['start']=11
    elif mutation=='prefix':r['dialogue_events'][0]['start']=1.5
    elif mutation=='anchor_missing':r['anchors'].pop()
    elif mutation=='unknown_anchor':r['anchors'][0]['id']='KF999'
    elif mutation=='keep_retime':r['anchors'][0]['decision']='KEEP'
    elif mutation=='drop_arrival':r['anchors'][1]['optimized_time']=4
    elif mutation=='anchor_nan':r['anchors'][0]['optimized_time']=float('inf')
    elif mutation=='relation':r['anchors'][0]['arrival_relation']={'dialogue_id':'D30','position':'AFTER'}
    elif mutation=='anchor_prefix':r['anchors'][0]['optimized_time']=1
    elif mutation=='anchor_order':r['anchors'][0].update(optimized_time=10,arrival_relation={'dialogue_id':'D27','position':'AFTER'})
    elif mutation=='prose_missing':r['detailed_description']=''
    elif mutation=='speech_text':r['detailed_description']+=prepared[NAMES[1]]['canonical'][0]['exact_dialogue']
    assert stage.compile_multi_keyframe_phase_b(prepared[NAMES[1]],r)['status']=='VALIDATION_FAILED'

@pytest.mark.parametrize('field,value',[('decision','DROP'),('optimized_time',14),('arrival_relation',{'dialogue_id':'D11','position':'BEFORE'})])
def test_alias_mismatch_rejected(prepared,field,value):
    r=saved(NAMES[2],'_mock_response');r['anchors'][-1][field]=value
    assert stage.compile_multi_keyframe_phase_b(prepared[NAMES[2]],r)['status']=='VALIDATION_FAILED'

@pytest.mark.parametrize('change',['hash','missing_previous','music','temporal_time','asset_hash','frozen_record',
    'binder_hash','temporal_alias_source','duplicate_anchor','outside_clip_anchor'])
def test_missing_evidence_not_covered(change):
    x=saved(NAMES[1] if change in ['duplicate_anchor','outside_clip_anchor'] else NAMES[2])
    if change=='hash':x['canonical_plan']['keyframes'][0]['description']='changed'
    elif change=='missing_previous':x['previous_video_path']=None
    elif change=='music':x['music_contract']['value']=None
    elif change=='temporal_time':x['physical_evidence']['temporal_anchors'][0]['time_seconds']=0
    elif change=='asset_hash':x['physical_evidence']['resource_hashes']['<Picture 1>']='bad'
    elif change=='frozen_record':x['frozen_record']={'answer':'must never read'}
    elif change=='binder_hash':x['physical_evidence']['reference_binder']['sha256']='changed'
    elif change=='temporal_alias_source':x['physical_evidence']['temporal_anchors'][0]['source']['id']='KF999'
    elif change=='duplicate_anchor':x['reference_manifest']['references'][1]['source_keyframe_index']=9
    elif change=='outside_clip_anchor':x['reference_manifest']['references'][1]['source_keyframe_index']=1
    if change in ['music','temporal_time','asset_hash','binder_hash','temporal_alias_source']:
        key='music_contract' if change=='music' else 'physical_evidence'
        x['source']['hashes'][key]=stage._snapshot_digest(x[key])
    if change in ['duplicate_anchor','outside_clip_anchor']:
        x['source']['hashes']['reference_manifest']=stage._snapshot_digest(x['reference_manifest'])
    assert stage.prepare_multi_keyframe_phase_b(x)['status']=='NOT_COVERED'

def test_only_explicit_runtime_adapter_calls_phase_b():
    for path in (Path(__file__).parents[1]/'app').rglob('*.py'):
        if path.name in {'h3_single_stage_experiment.py', 'h3_phase_b_pipeline.py'}:continue
        text=path.read_text()
        assert all(entry not in text for entry in ['prepare_multi_keyframe_phase_b',
            'preview_multi_keyframe_phase_b','compile_multi_keyframe_phase_b'])

def test_one_mock_call_no_retry(monkeypatch,prepared):
    monkeypatch.setattr(stage,'prepare_multi_keyframe_phase_b',lambda _:prepared[NAMES[1]])
    class Client:
        max_retries=0
        def __init__(self):self.calls=[]
        async def chat_completion(self,**request):
            self.calls.append(request)
            return {'success':True,'content':json.dumps(saved(NAMES[1],'_mock_response'))}
    c=Client();r=asyncio.run(stage.preview_multi_keyframe_phase_b({},llm=c))
    assert r['status']=='CANDIDATE_FOR_REVIEW' and r['llm_call_count']==len(c.calls)==1
    assert 'frozen_execution' not in c.calls[0]['user_content'] and len(c.calls[0]['images'])==14

def test_failure_not_retried(monkeypatch,prepared):
    monkeypatch.setattr(stage,'prepare_multi_keyframe_phase_b',lambda _:prepared[NAMES[1]])
    class Client:
        max_retries=0;calls=0
        async def chat_completion(self,**request):
            self.calls+=1
            raise TimeoutError('offline mock failure')
    c=Client();r=asyncio.run(stage.preview_multi_keyframe_phase_b({},llm=c))
    assert r['status']=='NOT_COVERED' and c.calls==r['llm_call_count']==1

def test_retrying_client_not_accepted(monkeypatch,prepared):
    monkeypatch.setattr(stage,'prepare_multi_keyframe_phase_b',lambda _:prepared[NAMES[1]])
    class Client:
        max_retries=1
        async def chat_completion(self,**kwargs):
            pytest.fail('retry-enabled client must not be called')
    assert asyncio.run(stage.preview_multi_keyframe_phase_b({},llm=Client()))['status']=='NOT_COVERED'

@pytest.fixture(scope='module')
def silent_prepared():
    cases = {}
    for name in NAMES:
        source = saved(name)
        original_states = deepcopy(source['canonical_plan']['keyframes'])
        original_transitions = deepcopy(source['canonical_plan']['transitions'])
        # Synthetic offline variant; explicitly not a new historical Canonical fixture.
        source['canonical_plan']['dialogue_timeline_source'] = []
        source['builder_input']['dialogue_timeline_source'] = []
        for key in ['canonical_plan', 'builder_input']:
            source['source']['hashes'][key] = stage._snapshot_digest(source[key])
        p = stage.prepare_multi_keyframe_phase_b(source)
        assert p['status'] == 'PREPARED', p
        assert source['canonical_plan']['keyframes'] == original_states
        assert source['canonical_plan']['transitions'] == original_transitions
        cases[name] = p
    return cases


def silent_response(name):
    response = saved(name, '_mock_response')
    response['dialogue_events'] = []
    for a in response['anchors']:
        a['arrival_relation'] = None
    response['detailed_description'] = '人物保持沉默，当前片段内的动作按 Canonical 顺序连续执行。'
    response['overall_soundscape'] = '有依据的场景环境与动作衣料声，无人声。'
    return response


@pytest.mark.parametrize('name', NAMES)
def test_silent_absolute_arrival_and_speech_authority(silent_prepared, name):
    from app.services.h3_phase_b_pipeline import preflight
    p = silent_prepared[name]; before = deepcopy(p)
    response = silent_response(name)
    r = stage.compile_multi_keyframe_phase_b(p, response)
    assert r['status'] == 'CANDIDATE_FOR_REVIEW', r
    assert preflight(p, r)['passed']
    assert p == before
    assert p['canonical'] == p['assigned'] == p['llm_input']['speech_slots'] == []
    assert p['llm_input']['speaker_bindings'] == {}
    assert r['execution_decisions']['timing']['dialogue_events'] == []
    assert r['execution_decisions']['gaps'] == []
    assert dialogue_events(r['prompt']) == [] and '(S1)' not in r['prompt']
    assert list(sections(r['prompt'])) == list(SECTIONS)
    assert sections(r['prompt'])['detailed_description'] == response['detailed_description']
    assert sections(r['prompt'])['overall_soundscape'] == response['overall_soundscape']
    assert 'All characters remain silent' in r['prompt']
    assert 'no speech, narration or additional vocalization' in r['prompt']
    retained = [a for a in r['execution_decisions']['anchor_decisions'] if a['decision'] != 'DROP']
    assert retained  # Silence never forces all anchors to DROP.
    for a in retained:
        assert a['arrival_relation'] is None
        assert f"at {a['optimized_time']}s in GENERATION_LOCAL_SECONDS" in r['prompt']
    assert all(r['review']['structure'].values()) and all(r['review']['structured_authority'].values())
    assert r['picture_audit']['passed'] and all(r['continuation_checks'].values())
    assert r['execution_decisions']['timing']['optimized_duration'] == response['optimized_duration']
    if p['continuation']:
        assert p['continuation']['overlap_seconds'] == 1.625
        assert '0–1.625s' in r['prompt'] and 'its existing audio' in r['prompt']
        assert len(p['llm_input']['previous_av']['preview_frames']) == 5
    if name == NAMES[2]:
        choices = {a['id']: a for a in r['execution_decisions']['anchor_decisions']}
        assert choices['KF6']['optimized_time'] == choices['clip-2-KF6']['optimized_time']
        assert r['temporal_manifest']['anchors'] == project_temporal_anchor_positions(
            [{**p['temporal_anchors'][0], 'time_seconds': choices['KF6']['optimized_time']}], response['optimized_duration'])
        assert not any(x['kind'] == 'TEMPORAL_ANCHOR' for x in r['picture_mapping'])


@pytest.mark.parametrize('mutation', ['fake_dialogue', 'fake_relation', 'fake_slot', 'fake_voice',
                                     'prefix', 'duration', 'drop_time', 'alias'])
def test_silent_invalid_contract_still_rejected(silent_prepared, mutation):
    name = NAMES[2]; p = silent_prepared[name]; response = silent_response(name)
    if mutation == 'fake_dialogue': response['dialogue_events'] = [{'id': 'D1', 'start': 2}]
    elif mutation == 'fake_relation': response['anchors'][0]['arrival_relation'] = {'dialogue_id': 'D1', 'position': 'BEFORE'}
    elif mutation == 'fake_slot': response['detailed_description'] += '[[SPEECH_1]]'
    elif mutation == 'fake_voice': response['detailed_description'] += '<Subject 1> (S1) says, <d>fake</d>'
    elif mutation == 'prefix': response['anchors'][0].update(decision='RETIME', optimized_time=1)
    elif mutation == 'duration': response['optimized_duration'] = 0.5
    elif mutation == 'drop_time': response['anchors'][0]['decision'] = 'DROP'
    elif mutation == 'alias': response['anchors'][-1]['optimized_time'] += 0.1
    assert stage.compile_multi_keyframe_phase_b(p, response)['status'] == 'VALIDATION_FAILED'


@pytest.mark.parametrize('name', NAMES)
def test_spoken_anchor_relation_remains_required(prepared, name):
    response = saved(name, '_mock_response')
    next(a for a in response['anchors'] if a['decision'] != 'DROP')['arrival_relation'] = None
    r = stage.compile_multi_keyframe_phase_b(prepared[name], response)
    assert r['status'] == 'VALIDATION_FAILED' and 'ANCHOR_RELATION_INVALID' in str(r['reasons'])


def test_saved_shot14_silent_clip_real_resources_and_contract():
    from app.services.h3_phase_b_pipeline import preflight
    snapshot = saved('shot14_c2_silent_temporal_extend')
    before = deepcopy(snapshot)
    p = stage.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
    assert p['status'] == 'PREPARED', p
    assert len(p['images']) == 4 + 2 + 5
    assert p['canonical'] == []
    assert p['llm_input']['clip']['start_time'] == 12.5
    assert p['llm_input']['clip']['end_time'] == 17
    assert [s['index'] for s in p['llm_input']['canonical']['owned_visual_states']] == [4, 5, 6]
    assert p['llm_input']['canonical']['carry_in_visual_state']['index'] == 3
    assert p['continuation']['source_sha256'] == 'af6ed6fd984023a442cdaf1c10f09decfe1b7c4b218a3ab04af116616f894b69'
    assert p['continuation']['overlap_seconds'] == 1.625
    r = stage.compile_multi_keyframe_phase_b(p, saved('shot14_c2_silent_temporal_extend', '_mock_response'))
    assert preflight(p, r)['passed'], r
    assert len(r['reference_manifest']['references']) == 4
    assert len(r['temporal_manifest']['anchors']) == 2
    assert not r['reference_manifest'].get('excluded_references')
    assert all(a['decision'] == 'RETIME' and a['arrival_relation'] is None for a in r['execution_decisions']['anchor_decisions'])
    assert snapshot == before


def assert_handoff_prose_preserved(p, response):
    """Contract/transport assertions only; mock prose cannot certify directing quality."""
    from app.services.h3_native_prompt import speaker_bindings
    from app.services.h3_phase_b_pipeline import preflight
    before = deepcopy((p, response))
    result = stage.compile_multi_keyframe_phase_b(p, response)
    assert result['status'] == 'CANDIDATE_FOR_REVIEW', result
    check = preflight(p, result)
    assert check['passed'], check
    assert (p, response) == before
    assert set(response) == {'optimized_duration', 'dialogue_events', 'anchors',
                             'detailed_description', 'overall_soundscape'}
    parts = sections(result['prompt'])
    assert list(parts) == list(SECTIONS)
    events = dialogue_events(result['prompt'])
    bindings = speaker_bindings(p['canonical'])
    assert [(e['speaker'], e['speaker_id'], e['exact_dialogue']) for e in events] == [
        (e['speaker'], bindings[e['speaker']], e['exact_dialogue']) for e in p['canonical']]
    # Exact per-slot preludes prove adjacency, not just presence somewhere in the Prompt.
    source = response['detailed_description']
    for i, event in enumerate(events, 1):
        prelude, source = source.split(f'[[SPEECH_{i}]]', 1)
        assert event['prelude'] == prelude
    restored = parts['detailed_description']
    for i, event in reversed(list(enumerate(events, 1))):
        restored = restored[:event['span_start']] + f'[[SPEECH_{i}]]' + restored[event['span_end']:]
    assert restored == response['detailed_description']
    assert parts['overall_soundscape'] == response['overall_soundscape']
    timing = result['execution_decisions']['timing']['dialogue_events']
    for event, fact, requested in zip(timing, p['canonical'], response['dialogue_events']):
        assert event['id'] == fact['id'] == requested['id']
        assert event['speaker'] == fact['speaker']
        assert event['optimized_start'] == requested['start']
        assert event['optimized_end'] - event['optimized_start'] == pytest.approx(fact['duration'])
    diagnostics = check['native_diagnostics']
    for key in ('speaker_switch_camera_evidence', 'speaker_switch_listener_settle',
                'speaker_switch_listener_scope'):
        assert key in diagnostics and key not in check['checks']
    assert check['director_semantics'].startswith('REVIEW_REQUIRED')
    if p['continuation']:
        assert all(e['optimized_start'] >= p['continuation']['overlap_seconds'] for e in timing)
        assert all(result['continuation_checks'].values())
    return result


@pytest.mark.parametrize('scenario', ['alternating', 'listener_reaction', 'multiple_listeners'])
def test_saved_c3_local_handoff_is_preserved_without_authority_changes(scenario):
    case = saved('test3_shot2_c3_speaker_handoff')
    p = case['prepared']; original = case['original_response']
    response = deepcopy(original)
    insertions = case['mock_handoff_insertions']
    if scenario == 'listener_reaction':
        insertions['SPEECH_3'] = (
            "The existing continuous view keeps <Subject 1>'s listening reaction readable. "
            '<Subject 1> keeps his mouth closed for this turn while <Subject 2> resumes speaking; '
            'camera attention does not transfer the utterance to the listener. ')
    elif scenario == 'multiple_listeners':
        insertions['SPEECH_3'] += (
            '<Subject 3>, <Subject 4> and <Subject 5> do not mouth the incoming words; '
            'they continue the authorized clothing, belt and mirror actions until the Canonical stop. ')
    for slot, prose in insertions.items():
        marker = f'[[{slot}]]'
        assert response['detailed_description'].count(marker) == 1
        response['detailed_description'] = response['detailed_description'].replace(marker, prose + marker)
    result = assert_handoff_prose_preserved(p, response)
    historical = stage.compile_multi_keyframe_phase_b(p, original)
    assert [e['speaker'] for e in p['canonical']] == ['<Subject 2>', '<Subject 1>', '<Subject 2>']
    assert [e['id'] for e in p['canonical']] == ['D7', 'D8', 'D9']
    for key in ('execution_decisions', 'picture_mapping', 'reference_manifest', 'temporal_manifest',
                'continuation_checks'):
        assert result[key] == historical[key]
    for section in ('subject_definitions', 'summary', 'retention_analysis', 'non_diegetic_music'):
        assert sections(result['prompt'])[section] == sections(historical['prompt'])[section]
    assert len(result['picture_mapping']) == 9 and result['temporal_manifest']['anchors'] == []
    assert p['continuation']['source_sha256'] == 'eced8e39fd99f5c13240df6302ff6f7426848ec8cbc528fdbe705f038929550a'
    assert p['execution_projection']['continuation_mode'] == 'EXTEND_ONLY'
    assert result['review']['native_prompt_diagnostics']['speaker_switch_camera_evidence'] is False
    # Removing only the test insertions restores all original camera/action text.
    restored = response['detailed_description']
    for prose in insertions.values():
        restored = restored.replace(prose, '', 1)
    assert restored == original['detailed_description']


@pytest.mark.parametrize('name', NAMES)
def test_handoff_prose_uses_existing_mode_and_prefix_contract(prepared, name):
    p = prepared[name]; response = saved(name, '_mock_response')
    previous, incoming = [e['speaker'] for e in p['canonical'][:2]]
    assert previous != incoming
    local = (f'{previous} finishes speaking and quietly listens during the following turn. '
             f'{incoming} naturally articulates while continuing the authorized action. ')
    response['detailed_description'] = response['detailed_description'].replace('[[SPEECH_2]]', local + '[[SPEECH_2]]')
    result = assert_handoff_prose_preserved(p, response)
    baseline = stage.compile_multi_keyframe_phase_b(p, saved(name, '_mock_response'))
    for key in ('execution_decisions', 'picture_mapping', 'reference_manifest', 'temporal_manifest', 'continuation_checks'):
        assert result[key] == baseline[key]


def test_consecutive_same_speaker_does_not_gain_compiler_handoff(prepared):
    p = prepared[NAMES[0]]; response = saved(NAMES[0], '_mock_response')
    assert p['canonical'][-2]['speaker'] == p['canonical'][-1]['speaker'] == '<Subject 1>'
    response['detailed_description'] = response['detailed_description'].replace(
        '[[SPEECH_5]]\n[[SPEECH_6]]',
        '<Subject 1> continues naturally through both utterances while retaining the authorized action. '
        '[[SPEECH_5]]\n[[SPEECH_6]]')
    result = assert_handoff_prose_preserved(p, response)
    assert dialogue_events(result['prompt'])[-1]['prelude'] == '\n'


def test_offscreen_speech_and_visible_listeners_retain_motion():
    from test_h3_phase_b_subject_references import shot17_case
    p, response, _ = shot17_case()
    original = deepcopy(response)
    local = ('<Subject 3> speaks from outside the closed door and remains off-screen for this utterance; '
             'no visible articulation or entrance is required. <Subject 1> and <Subject 2> listen without '
             'mouthing these words while continuing their authorized walking, clothing and hand actions. ')
    response['detailed_description'] = response['detailed_description'].replace('[[SPEECH_3]]', local + '[[SPEECH_3]]')
    result = assert_handoff_prose_preserved(p, response)
    baseline = stage.compile_multi_keyframe_phase_b(p, original)
    assert result['execution_decisions'] == baseline['execution_decisions']
    assert result['picture_mapping'] == baseline['picture_mapping']
    assert dialogue_events(result['prompt'])[2]['speaker'] == '<Subject 3>'
    assert response['detailed_description'].replace(local, '', 1) == original['detailed_description']


@pytest.mark.parametrize('mutation', ['dialogue_id_in_prose', 'speaker_tag', 'handoffs_field'])
def test_handoff_does_not_delegate_dialogue_authority(mutation):
    case = saved('test3_shot2_c3_speaker_handoff')
    response = case['original_response']
    if mutation == 'dialogue_id_in_prose':
        response['detailed_description'] += ' During D9 the listener is quiet.'
    elif mutation == 'speaker_tag':
        response['detailed_description'] += ' <Subject 2> (S1) speaks.'
    else:
        response['handoffs'] = []
    result = stage.compile_multi_keyframe_phase_b(case['prepared'], response)
    assert result['status'] == 'VALIDATION_FAILED'
