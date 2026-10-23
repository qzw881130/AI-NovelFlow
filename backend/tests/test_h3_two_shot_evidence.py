import copy,json
from pathlib import Path
import pytest
from app.services.h3_execution_optimizer import check_authority

def sample():return json.loads((Path(__file__).parent/'fixtures/h3_shot5_two_shot_evidence.json').read_text())
def audit(s):return check_authority(s['raw_prompt'],s['output'],s['authority'],s['initial'],s['limits'])

def test_same_explicit_pair_can_use_both_faces_without_repeating_ids_in_excerpt():
    s=sample();before=copy.deepcopy(s);a=audit(s)
    assert a['blocking_findings']==['reference_authority_scope']
    assert a['checks']['speaker_switch_camera_evidence'] and s==before

@pytest.mark.parametrize('case',['negated','unreadable','third_actor','missing_pair','evidence_from_later'])
def test_pair_must_be_readable_in_exact_preceding_prelude(case):
    s=sample();o=s['output'];h=o['av_timeline']['handoffs'][0];e=h['prompt_evidence']['existing_view_excerpt']
    replacement=e
    if case=='negated':replacement=e.replace('keeps both','does not keep both')
    elif case=='unreadable':replacement=e.replace('readable','unreadable')
    elif case=='third_actor':o['optimized_prompt']=o['optimized_prompt'].replace('His eyes soften','<Subject 3> watches. His eyes soften')
    elif case=='missing_pair':o['optimized_prompt']=o['optimized_prompt'].replace('<Subject 2> remains a quiet listener','His companion remains a quiet listener')
    elif case=='evidence_from_later':h['prompt_evidence']['existing_view_excerpt']='That same established ensemble view continues to hold <Subject 2>'
    if replacement!=e:
        o['optimized_prompt']=o['optimized_prompt'].replace(e,replacement)
        h['prompt_evidence']['existing_view_excerpt']=replacement
    assert not audit(s)['checks']['speaker_switch_camera_evidence'],case
