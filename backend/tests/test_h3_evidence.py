import copy
import json
from pathlib import Path
import pytest
from app.services.h3_evidence import resolve_excerpt
from app.services.h3_execution_optimizer import check_authority

@pytest.fixture
def original():
    return json.loads((Path(__file__).parent/'fixtures/h3_v5_evidence_mismatch.json').read_text())

def audit(sample):
    return check_authority(sample['raw_prompt'],sample['output'],sample['authority'],sample['initial'],sample['limits'])

def test_real_v5_output_resolves_three_false_positives_without_changing_raw_output(original):
    before=copy.deepcopy(original);result=audit(original)
    assert result['passed']
    assert all(result['checks'][k] for k in ['canonical_visual_requirement_trace','anchor_decision_semantics','anchor_arrival_relation'])
    assert result['evidence_provenance']['status']=='EVIDENCE_MISMATCH'
    assert result['evidence_provenance']['mismatches']==['requirements.0.prompt','anchors.0.prompt','anchors.0.relation']
    for path in result['evidence_provenance']['mismatches']:
        e=result['resolved_evidence']['entries'][path]
        assert 'with hands lowered' in e['excerpt'] and 'with hands lowered' not in e['supplied_excerpt']
        assert e['excerpt'] in original['output']['optimized_prompt']
    assert original==before

@pytest.mark.parametrize('text,hint',[
    ('A does not raise his hands.','A does raise his hands.'),
    ('A raises his hands.','A never raises his hands.'),
    ('<Subject 4> raises empty hands.','<Subject 1> raises empty hands.'),
    ('A stands. A stands.','A stands.'),
])
def test_polarity_participant_changes_and_ambiguous_spans_are_not_fuzzy_passes(text,hint):
    assert resolve_excerpt(text,hint)['status']!='RESOLVED'

def test_punctuation_and_whitespace_resolve_to_real_text():
    text='A raises both hands, palms up.'
    e=resolve_excerpt(text,'A raises hands palms up')
    assert e['excerpt']==text and e['mismatch']


def test_cjk_quote_can_omit_an_incidental_camera_clause():
    text='明亮的大厅，王座位于后方；全景，机位朝向王座。可见甲、乙、丙三人。'
    hint='明亮的大厅，王座位于后方；可见甲、乙、丙三人。'
    e=resolve_excerpt(text,hint)
    assert e['excerpt']==text and e['mismatch']
    assert resolve_excerpt('甲不再站立，乙倾听。','甲站立，乙倾听。')['status']=='UNRESOLVED'

@pytest.mark.parametrize('kind',[
    'missing_action','contradictory_action','wrong_speaker','wrong_dialogue','wrong_identity',
    'wrong_reference','wrong_arrival_order','illegal_keep_time','wrong_actor_action',
])
def test_real_content_errors_still_block(original,kind):
    o=original['output'];p=o['optimized_prompt']
    action=o['canonical_visual_requirements'][4]['prompt_excerpt']
    if kind=='missing_action':p=p.replace(action,'')
    elif kind=='contradictory_action':p=p.replace('while no physical fabric or other object appears','while physical fabric or another object appears')
    elif kind=='wrong_actor_action':p=p.replace(action,action.replace('<Subject 4>','<Subject 3>'))
    elif kind=='wrong_speaker':p=p.replace('<Subject 1> (S3) asks, <d>[Chinese] 听说','<Subject 3> (S1) asks, <d>[Chinese] 听说')
    elif kind=='wrong_dialogue':p=p.replace('它有多漂亮？','它在哪里？')
    elif kind=='wrong_identity':p=p.replace('<Subject 1> is 皇帝,','<Subject 1> is 骗子1,')
    elif kind=='wrong_reference':p=p.replace('<Picture 5> is identity-only guidance for <Subject 1>','<Picture 6> is identity-only guidance for <Subject 1>')
    elif kind=='wrong_arrival_order':
        e=o['av_timeline']['anchors'][2]['prompt_excerpt'];p=p.replace(e,'').replace('<Subject 4> (S2) says, <d>[Chinese] 它轻',e+' <Subject 4> (S2) says, <d>[Chinese] 它轻')
    elif kind=='illegal_keep_time':o['av_timeline']['anchors'][0]['optimized_time']=1
    o['optimized_prompt']=p
    result=audit(original)
    assert not result['passed'],kind
    if kind=='missing_action':
        assert 'canonical_visual_requirement_consistency' in result['blocking_findings']
        assert result['semantic_consistency']['status']=='REVIEW_REQUIRED'
    if kind=='wrong_arrival_order':assert 'anchor_arrival_relation' in result['blocking_findings']

def test_handoff_metadata_can_resolve_without_weakening_listener_contract(original):
    h=original['output']['av_timeline']['handoffs'][0]
    h['prompt_evidence']['listeners']=h['prompt_evidence']['listeners'].replace('naturally ','')
    result=audit(original)
    assert result['passed'] and 'handoffs.0.listeners' in result['evidence_provenance']['mismatches']
    original['output']['optimized_prompt']=original['output']['optimized_prompt'].replace(h['prompt_evidence']['listeners'].replace('listen with','listen naturally with'),'All other characters talk.')
    assert not audit(original)['passed']
