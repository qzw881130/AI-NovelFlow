import copy
import json
from pathlib import Path
import pytest
from app.services.h3_execution_optimizer import check_authority

def sample():
    return json.loads((Path(__file__).parent/'fixtures/h3_shot5_ellipsis.json').read_text())

def audit(s):
    return check_authority(s['raw_prompt'],s['output'],s['authority'],s['initial'],s['limits'])

def test_real_output_preserves_source_and_prompt_while_resolving_explicit_ellipsis():
    s=sample();before=copy.deepcopy(s);a=audit(s)
    assert a['passed'],a['blocking_findings']
    for index in (0,2,4):
        e=a['resolved_evidence']['entries'][f'requirements.{index}.source']
        assert e['method']=='CANONICAL_EXPLICIT_ELLIPSIS' and e['mismatch']
        r=s['output']['canonical_visual_requirements'][index]
        source=next(x['text'] for x in s['authority']['anchor_policy']['canonical_visual_sources'] if x['id']==r['source_id'])
        assert all(source[x['start']:x['end']]==x['excerpt'] for x in e['resolved_spans'])
    assert s==before

@pytest.mark.parametrize('case',['wrong_source','missing','order','wrong_actor','omitted_negation','other_actor_action','substring','ambiguous'])
def test_ellipsis_never_invents_or_reassigns_evidence(case):
    s=sample();r=s['output']['canonical_visual_requirements'][2]
    source=next(x for x in s['authority']['anchor_policy']['canonical_visual_sources'] if x['id']==r['source_id'])
    if case=='wrong_source':r['source_id']='transition_2'
    elif case=='missing':r['source_excerpt']=r['source_excerpt'].replace('明确指向','用力抓住')
    elif case=='order':r['source_excerpt']='；'.join(reversed(r['source_excerpt'].split('；')))
    elif case=='wrong_actor':r['requirement']=r['requirement'].replace('Subject 1','Subject 3')
    elif case=='omitted_negation':source['text']=source['text'].replace('并将一只手','但没有将一只手')
    elif case=='other_actor_action':source['text']=source['text'].replace('并将一只手','仆人1将一只手')
    elif case=='substring':r['source_excerpt']=r['source_excerpt'].replace('将一只手明确指向骗子2左手附近的空处','明确指向骗子2左手')
    elif case=='ambiguous':source['text']+='。'+source['text']
    a=audit(s)
    assert not a['checks']['canonical_visual_requirement_trace'],case

@pytest.mark.parametrize('case',['wrong_picture_kind','dropped_start','seated_negated','seated_wrong_actor','wrong_speaker','missing_action'])
def test_provenance_does_not_bypass_final_contract(case):
    s=sample();p=s['output']['optimized_prompt']
    if case=='wrong_picture_kind':s['authority']['reference_bindings'][0]['type']='CHARACTER_IDENTITY'
    elif case=='dropped_start':
        s['output']['av_timeline']['anchors'][0]['decision']='DROP'
        assert not audit(s)['checks']['reference_authority_scope']
    elif case=='seated_negated':p=p.replace('<Subject 1> and <Subject 2> stay seated','<Subject 1> and <Subject 2> do not stay seated')
    elif case=='seated_wrong_actor':p=p.replace('<Subject 1> and <Subject 2> stay seated','<Subject 3> and <Subject 2> stay seated')
    elif case=='wrong_speaker':p=p.replace('<Subject 1> (S1) says','<Subject 2> (S1) says',1)
    elif case=='missing_action':p=p.replace(s['output']['canonical_visual_requirements'][2]['prompt_excerpt'],'')
    s['output']['optimized_prompt']=p
    assert not audit(s)['passed'],case
