"""Continuation source can be named by an explicit opening carry-in instruction."""
import copy
import json
from pathlib import Path
import pytest
from app.services.h3_execution_optimizer import check_authority


def sample():
    return json.loads((Path(__file__).parent/'fixtures/h3_v5_c6_opening_authority.json').read_text())


def audit(s):
    return check_authority(s['raw_prompt'],s['output'],s['authority'],s['initial'],s['limits'])


def test_saved_c6_opening_source_and_retention_scope_pass_without_rewriting_output():
    s=sample();before=copy.deepcopy(s);r=audit(s)
    assert r['passed'],r['blocking_findings']
    assert r['checks']['reference_authority_scope']
    assert r['checks']['stable_speaker_ids'] and r['checks']['continuation_new_speech_budget']
    assert s==before


@pytest.mark.parametrize('case',['standard','unverified','source_absent','source_late','source_negated',
    'retention_not_carried','not_video_source','retention_scope_absent'])
def test_opening_fallback_requires_verified_source_positive_opening_and_retention(case):
    s=sample();p=s['output']['optimized_prompt']
    if case=='standard':s['authority'].pop('continuation')
    elif case=='unverified':s['authority']['continuation']['binding_verified']=False
    elif case=='source_absent':p=p.replace('Continue the shared incoming footage','Continue the palace scene')
    elif case=='source_late':
        p=p.replace('Continue the shared incoming footage','Continue the palace scene')
        p += '\nContinue the shared incoming footage.'
    elif case=='source_negated':p=p.replace('Continue the shared incoming footage','Do not continue the shared incoming footage')
    elif case=='retention_not_carried':p=p.replace('Carry forward the incoming posture','Invent a new posture')
    elif case=='not_video_source':p=p.replace('Continue the shared incoming footage','Continue the shared incoming picture')
    elif case=='retention_scope_absent':
        a=p.index('retention_analysis:');z=p.index('detailed_description:')
        p=p[:a]+'retention_analysis:\nCarry forward the incoming state.\n\n'+p[z:]
    s['output']['optimized_prompt']=p;before=copy.deepcopy(s)
    assert not audit(s)['checks']['reference_authority_scope']
    assert s==before


@pytest.mark.parametrize('case',['wrong_identity','wrong_speaker','missing_speaker_id','wrong_text','early_dialogue','wrong_projection'])
def test_opening_authority_does_not_mask_real_binding_or_canonical_conflicts(case):
    s=sample();p=s['output']['optimized_prompt']
    if case=='wrong_identity':p=p.replace('<Picture 4> supplies identity only','<Picture 5> supplies identity only',1)
    elif case=='wrong_speaker':p=p.replace('<Subject 2> (S1) says','<Subject 1> (S1) says',1)
    elif case=='missing_speaker_id':p=p.replace('<Subject 2> (S1) says','<Subject 2> says',1)
    elif case=='wrong_text':p=p.replace('怎么？','好的。')
    elif case=='early_dialogue':s['output']['av_timeline']['dialogue_events'][0]['optimized_start']=.5
    elif case=='wrong_projection':s['output']['reference_projection'][0]['source_picture']='<Picture 2>'
    s['output']['optimized_prompt']=p
    assert not audit(s)['passed'],case
