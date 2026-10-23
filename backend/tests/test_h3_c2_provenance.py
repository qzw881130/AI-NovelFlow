"""Real saved C2 regression plus event/actor/scope negative controls."""
import copy
import json
from pathlib import Path
import pytest
from app.services.h3_execution_optimizer import check_authority
from app.services.h3_evidence import resolve_canonical_excerpt

FIXTURE=Path(__file__).parent/'fixtures/h3_v5_c2_repeated_provenance.json'

def sample():return json.loads(FIXTURE.read_text())
def audit(s):return check_authority(s['raw_prompt'],s['output'],s['authority'],s['initial'],s['limits'])


def test_saved_c2_passes_without_changing_original_output():
    s=sample();original=copy.deepcopy(s);r=audit(s)
    assert r['passed'],r['blocking_findings']
    assert r['checks']['stable_speaker_ids'] and r['checks']['continuation_new_speech_budget']
    e=r['resolved_evidence']['entries']['requirements.8.source']
    assert e['status']=='RESOLVED' and e['event_ids']==['D7','D8','D9','D10']
    assert e['start'] is None and e['end'] is None
    assert len(e['locations'])==4 and all(loc['selected'] for loc in e['locations'])
    source=next(x['text'] for x in s['authority']['anchor_policy']['canonical_visual_sources'] if x['id']=='opening_state')
    assert all(source[loc['start']:loc['end']]==e['supplied_excerpt'] for loc in e['locations'])
    assert s==original


@pytest.mark.parametrize('mode',['standard','unverified'])
def test_preceding_video_alias_is_not_a_standard_or_unverified_authority(mode):
    s=sample()
    if mode=='standard':s['authority'].pop('continuation')
    else:s['authority']['continuation']['binding_verified']=False
    assert not audit(s)['checks']['reference_authority_scope']


@pytest.mark.parametrize('kind',['missing','wrong_source','wrong_actor','wrong_event','wrong_count','unscoped',
                                  'wrong_speaker','missing_speaker_id','wrong_picture','too_early'])
def test_real_errors_remain_blocked(kind):
    s=sample();r=s['output']['canonical_visual_requirements'][8]
    if kind=='missing':r['source_excerpt']='not present in canonical source'
    elif kind=='wrong_source':r['source_id']='transition_1'
    elif kind=='wrong_actor':r['requirement']=r['requirement'].replace('<Subject 3>','<Subject 4>')
    elif kind=='wrong_event':r['requirement']=r['requirement'].replace('all four utterances','D99')
    elif kind=='wrong_count':r['requirement']=r['requirement'].replace('all four utterances','all three utterances')
    elif kind=='unscoped':r['requirement']=r['requirement'].replace('all four utterances','the utterance')
    elif kind=='wrong_speaker':s['output']['optimized_prompt']=s['output']['optimized_prompt'].replace('<Subject 3> (S1) says','<Subject 4> (S1) says',1)
    elif kind=='missing_speaker_id':s['output']['optimized_prompt']=s['output']['optimized_prompt'].replace('<Subject 3> (S1) says','<Subject 3> says',1)
    elif kind=='wrong_picture':s['output']['optimized_prompt']=s['output']['optimized_prompt'].replace('<Picture 3> supplies identity only for <Subject 1>.','<Picture 3> supplies identity only for <Subject 4>.')
    elif kind=='too_early':s['output']['av_timeline']['dialogue_events'][0]['optimized_start']=.1
    assert not audit(s)['passed'],kind


def event_source():
    q='The speaking face remains readable.'
    text=f'D1:\n  speaker: <Subject 1>\n  exact_dialogue: 一。\n  {q}\nD2:\n  speaker: <Subject 2>\n  exact_dialogue: 二。\n  {q}'
    a={'dialogue_events':[{'id':'D1','speaker':'<Subject 1>','exact_dialogue':'一。'},
                          {'id':'D2','speaker':'<Subject 2>','exact_dialogue':'二。'}]}
    return q,text,a


def test_identical_words_across_different_actors_need_event_ownership():
    q,text,a=event_source()
    req={'source_excerpt':q,'requirement':'Keep <Subject 1> readable for all two utterances.'}
    assert resolve_canonical_excerpt(text,req,a)['status']!='RESOLVED'
    req['requirement']='Keep <Subject 1> readable for D1.'
    e=resolve_canonical_excerpt(text,req,a)
    assert e['status']=='RESOLVED' and len(e['locations'])==2
    assert [loc['selected'] for loc in e['locations']]==[True,False]
    req['requirement']='Keep <Subject 1> readable for D2.'
    assert resolve_canonical_excerpt(text,req,a)['status']=='OWNERSHIP_CONFLICT'


def test_repeated_words_in_different_source_sections_are_not_promoted():
    q,text,a=event_source()
    text+='\nother_scope:\n'+q
    req={'source_excerpt':q,'requirement':'Keep <Subject 1> readable for D1.'}
    assert resolve_canonical_excerpt(text,req,a)['status']=='AMBIGUOUS'


def test_canonical_event_header_mismatch_is_not_an_exact_match_pass():
    q,text,a=event_source();text=text.replace('speaker: <Subject 2>','speaker: <Subject 1>')
    req={'source_excerpt':q,'requirement':'Keep <Subject 1> readable for D1.'}
    assert resolve_canonical_excerpt(text,req,a)['status']=='OWNERSHIP_CONFLICT'
