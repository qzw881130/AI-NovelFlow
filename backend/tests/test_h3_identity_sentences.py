import copy
import json
from pathlib import Path
import pytest
from app.services.h3_execution_optimizer import check_authority, _identity_picture_subjects
from app.services.h3_preflight_repair import deterministic_candidate


def sample():
    return json.loads((Path(__file__).parent / 'fixtures/h3_shot5_identity_sentences.json').read_text())


def audit(s):
    return check_authority(s['raw_prompt'], s['output'], s['authority'], s['initial'], s['limits'])


def test_identity_definitions_do_not_bind_later_unrelated_action_subject():
    s = sample()
    before = copy.deepcopy(s)
    normalized, changes = deterministic_candidate(s['original_output'], s['authority'])
    assert normalized == s['output']
    assert [c['code'] for c in changes] == ['H3_SECTION_HEADER_INDENTATION']
    assert audit(s)['passed']
    assert s == before


@pytest.mark.parametrize('case', ['rebound', 'extra_mapping', 'ambiguous', 'missing_definition'])
def test_real_wrong_or_missing_identity_mapping_still_fails(case):
    s = sample()
    p = s['output']['optimized_prompt']
    if case == 'rebound':
        p = p.replace('<Picture 2> is identity-only guidance for this Subject',
                      '<Picture 2> is identity-only guidance for <Subject 2>')
    elif case == 'extra_mapping':
        p = p.replace('retention_analysis:\n',
                      'retention_analysis:\n<Picture 2> supplies identity for <Subject 3>. ')
    elif case == 'ambiguous':
        p = p.replace('for this Subject', 'for <Subject 1> and <Subject 2>', 1)
    else:
        p = p.replace('<Picture 2> is identity-only guidance for this Subject;',
                      'Identity remains stable;')
    s['output']['optimized_prompt'] = p
    assert not audit(s)['checks']['picture_binding_<Picture 2>']


def test_anaphora_cannot_borrow_another_line_or_undeclared_subject():
    assert _identity_picture_subjects('<Subject 1> is Alice.\n<Picture 2> is identity for this Subject.', '<Picture 2>') == set()
    assert _identity_picture_subjects('<Picture 2> preserves identity. <Subject 3> stays seated.', '<Picture 2>') == set()
