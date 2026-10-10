"""Read-only production regressions and negative controls for both #14 modes."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

from app.services import h3_continuation as cont
from app.services import h3_execution_optimizer as opt
from app.services.h3_anchor_policy import project_reference_manifest
from app.services.h3_native_prompt import check_native_prompt

FIXTURES = Path(__file__).parent / 'fixtures'

def sample(name):
    return json.loads((FIXTURES / f'h3_v5_{name}.json').read_text())

def audit(s):
    return opt.check_authority(s['raw_prompt'], s['output'], s['authority'], s['initial'], s['limits'])

@pytest.fixture
def physical(monkeypatch,tmp_path):
    w=NS(**json.loads((FIXTURES/'h3_continuation_workflow.json').read_text()))
    path=tmp_path/'previous.mp4';path.write_bytes(b'source')
    av={'sha256':'original-source-sha','frame_count':362,'fps':24,'timebase':'1/24','has_audio':True}
    context={'previous_clip':{'result_url':'/api/files/previous.mp4','generated_by_task_id':'approved-c1','physical_output':copy.deepcopy(av)}}
    monkeypatch.setattr(cont,'url_to_local_path',lambda value: str(path) if value=='/api/files/previous.mp4' else None)
    monkeypatch.setattr(cont,'probe_clip_av',lambda _:copy.deepcopy(av))
    return w,str(path),context

@pytest.fixture
def continuation(physical):
    return cont.continuation_contract(physical[0],'EXTEND',physical[1],physical[2])


def test_approved_c1_remains_equivalent_without_continuation():
    s=sample('approved_c1');before=copy.deepcopy(s);r=audit(s)
    assert r['passed'],r['blocking_findings']
    assert len(s['authority']['reference_bindings'])==9
    assert s['authority']['anchor_policy']['catalog']
    assert 'continuation' not in r['resolved_authority']['authority']
    assert not any(k.startswith('continuation_') for k in r['checks'])
    record={'status':'OPTIMIZED','authority_check':r,'output':s['output'],'optimized_prompt':s['output']['optimized_prompt']}
    assert opt.effective_execution_duration(s['initial']['duration'],record,s['limits'])['effective_duration']==15
    assert s==before


def test_original_c2_four_false_blocks_resolve_but_real_budget_still_fails(continuation):
    s=sample('previous_c2');s['authority']['continuation']=continuation;before=copy.deepcopy(s);r=audit(s)
    for name in ['subject_binding','reference_authority_scope','blocking_preservation_wording','authority_echo_preserved']:
        assert r['checks'][name],name
    assert r['resolved_authority']['authority']['subject_bindings']=={
        '<Subject 1>':'皇帝','<Subject 2>':'宫廷总管','<Subject 3>':'骗子1','<Subject 4>':'骗子2'}
    refs=r['resolved_authority']['authority']['reference_bindings']
    assert [r['subject'] for r in refs]==[None,'<Subject 3>','<Subject 1>','<Subject 2>','<Subject 4>']
    assert r['resolved_authority']['echo_status']=='AUTHORITY_ECHO_MISMATCH'
    assert any('canonical_visual_sources[0].text' in d['path'] for d in r['resolved_authority']['echo_differences'])
    assert not r['passed']
    assert set(r['blocking_findings'])=={'continuation_dialogue_after_context','continuation_new_speech_budget'}
    assert not s['output']['av_timeline']['anchors'] and s==before


@pytest.mark.parametrize('line_index', range(4))
def test_every_same_speaker_utterance_requires_its_own_id(continuation, line_index):
    # Saved real C2 output: four consecutive lines by Subject3 / S1. Removing
    # any one ID must fail, even though the surrounding prose names the actor.
    import re
    s=sample('previous_c2');s['authority']['continuation']=continuation
    original=s['output']['optimized_prompt']
    assert audit(s)['checks']['stable_speaker_ids']
    occurrences=list(re.finditer(r'<Subject 3> \(S1\)', original))
    assert len(occurrences)==4
    m=occurrences[line_index]
    s['output']['optimized_prompt']=original[:m.start()]+'<Subject 3>'+original[m.end():]
    checked=audit(s)
    assert not checked['checks']['stable_speaker_ids']
    assert not checked['checks']['native_dialogue_markup']
    assert s['output']['optimized_prompt'].count('<d>')==4


@pytest.mark.parametrize('punctuation',[',','，','.','。',';','；'])
def test_multilingual_name_delimiters(punctuation):
    assert opt.subject_bindings(f'<Subject 1> is 皇帝{punctuation}long description')=={'<Subject 1>':'皇帝'}


@pytest.mark.parametrize('mutation,check',[
    (lambda p:p.replace('<Subject 1> is 皇帝,','<Subject 1> is 骗子1,'),'subject_binding'),
    (lambda p:p.replace('<Subject 3> (S1) says,','<Subject 4> (S1) says,'),'dialogue_ids_speakers_text_order'),
    (lambda p:p.replace('亮得像太阳落在湖面上的光。','不是原句。'),'dialogue_ids_speakers_text_order'),
    (lambda p:p.replace('<Picture 3> supplies permanent identity only for <Subject 1>.','<Picture 3> supplies permanent identity only for <Subject 4>.'),'picture_binding_<Picture 3>'),
    (lambda p:p.replace('<Subject 1> remains seated on the high-backed throne;','<Subject 1> stands up from the high-backed throne;'),'no_acquisition_reblocking_<Subject 1>'),
    (lambda p:p.replace('<Subject 3> remains anchored on the left,','<Subject 3> walks to the right,'),'canonical_floor_position_<Subject 3>'),
    (lambda p:p.replace('His hands continue to indicate empty air.','His hands hold real cloth.'),'canonical_visual_requirement_consistency'),
    (lambda p:p+'\n<Subject 5> is a new guard.','subject_set'),
])
def test_actual_semantic_errors_still_block(continuation,mutation,check):
    s=sample('previous_c2');s['authority']['continuation']=continuation
    s['output']['optimized_prompt']=mutation(s['output']['optimized_prompt'])
    assert not audit(s)['checks'][check]


def test_explicit_wrong_manifest_subject_is_not_repaired(continuation):
    s=sample('previous_c2');s['authority']['continuation']=continuation
    s['authority']['reference_bindings'][2]['subject']='<Subject 4>'
    r=audit(s)
    assert not r['checks']['canonical_manifest_subject_consistent']
    assert r['resolved_authority']['authority']['reference_bindings'][2]['subject']=='<Subject 4>'


def test_standard_reference_authority_not_relaxed_by_previous_words():
    s=sample('previous_c2');r=audit(s)
    assert not r['checks']['reference_authority_scope']
    assert not any(k.startswith('continuation_') for k in r['checks'])


def test_standard_no_kf_is_not_continuation():
    assert cont.continuation_contract(None,'SINGLE_FRAME',None,{}) is None
    runtime,images=opt.build_runtime_input('No KF and no Previous Video.','SINGLE_FRAME',{'planned_duration':4})
    assert runtime['execution_mode']=='STANDARD_GENERATION' and not images
    assert 'continuation' not in runtime['immutable_authority']
    assert runtime['initial_execution_timing']['duration']==4


def test_real_workflow_has_inclusive_duration_and_shared_origin(continuation):
    c=continuation
    assert c['context_frames']==39 and c['earliest_new_dialogue']==1.625
    assert c['audio_hard_preserve_until']==1.425 and c['audio_feather_until']==1.625
    assert c['cumulative_start_frame']==323
    assert cont.target_frames(15)==362
    # Current H3 snaps a nominal 10 seconds to 243 frames; 240+240-39 is
    # the user's abstract counting example, not this node's 17n+5 lattice.
    assert 240+240-39==441
    assert cont.target_frames(10)==243
    assert 362+cont.target_frames(15)-39==685


def test_synthetic_feasible_schedule_is_not_shifted_or_extended_twice(continuation):
    events=[{'start_time':1.625,'end_time':4.625},{'start_time':4.825,'end_time':8.575},
            {'start_time':8.775,'end_time':10.775},{'start_time':10.975,'end_time':14.225}]
    before=copy.deepcopy(events)
    assert all(cont.check_continuation_timing(continuation,events,14.325).values())
    assert events==before
    assert not cont.check_continuation_timing(continuation,[{'start_time':1.5,'end_time':2.5}],4)['continuation_dialogue_after_context']


def test_configuration_not_a_global_39_frame_rule(physical):
    w,path,ctx=physical;graph=json.loads(w.workflow_json)
    graph['37']['inputs']['value']=90
    graph['65']['inputs']['context_frames']=graph['65']['inputs']['video_overlap_frames']=90
    w.workflow_json=json.dumps(graph)
    c=cont.continuation_contract(w,'EXTEND',path,ctx)
    assert c['context_frames']==90 and c['earliest_new_dialogue']==3.75
    assert cont.continuation_contract(None,'MULTI_KEYFRAME',None,{}) is None


@pytest.mark.parametrize('kind',['missing_source','wrong_source','wrong_hash','wrong_sampler','wrong_mode','wrong_context','missing_contract'])
def test_illegal_continuation_binding_fails(physical,kind):
    w,path,ctx=physical;graph=json.loads(w.workflow_json);cap='EXTEND'
    if kind=='missing_source':path=None
    elif kind=='wrong_source':path=path+'.other'
    elif kind=='wrong_hash':ctx['previous_clip']['physical_output']['sha256']='wrong'
    elif kind=='wrong_sampler':graph['3']['inputs']['latent_image']=['55',1]
    elif kind=='wrong_mode':cap='GENERATE'
    elif kind=='wrong_context':graph['37']['inputs']['value']=40
    elif kind=='missing_contract':ctx={}
    w.workflow_json=json.dumps(graph)
    with pytest.raises(ValueError):cont.continuation_contract(w,cap,path,ctx)


def test_continuation_with_kf_keeps_both_contracts(continuation):
    s=sample('approved_c1');s['authority']['continuation']=continuation;r=audit(s)
    for key in ['anchor_decisions_complete','anchor_decision_semantics','anchor_arrival_relation','reference_projection_consistent','drop_binding_supported']:
        assert r['checks'][key]
    s['output']['av_timeline']['anchors'][0]['decision']='INVALID'
    assert not audit(s)['checks']['anchor_decision_semantics']
    assert not audit(s)['checks']['continuation_dialogue_after_context']


def test_drop_all_temporal_anchors_leaves_previous_av_intact(continuation):
    manifest={'anchors':[{'anchor_id':'KF1','time_seconds':2,'local_path':'kf1.png'}]}
    record={'status':'OPTIMIZED','output':{'av_timeline':{'optimized_duration':5,'anchors':[
        {'id':'KF1','decision':'DROP','optimized_time':None}]}}}
    before=copy.deepcopy(continuation)
    projected=opt.retime_temporal_manifest(manifest,record)
    assert projected['anchors']==[] and projected['excluded_anchors']==manifest['anchors']
    assert continuation==before and continuation['context_frames']==39


@pytest.mark.parametrize('duration',[4,12.8,14.325,14.5,15])
def test_target_frame_prediction_matches_frozen_expression(duration):
    graph=json.loads(json.loads((FIXTURES/'h3_continuation_workflow.json').read_text())['workflow_json'])
    expression=graph['106']['inputs']['expression']
    assert cont.target_frames(duration)==eval(expression,{'__builtins__':{}},{'a':duration,'round':round,'max':max})
