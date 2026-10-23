import copy

import pytest

from app.services.h3_evidence import resolve_canonical_excerpt


RULE = 'LOCAL_MOTION / SPATIALLY_ANCHORED; no explicit translational assignment'
BINDINGS = {'<Subject 1>':'甲', '<Subject 2>':'乙', '<Subject 3>':'丙'}


@pytest.fixture
def case():
    source = 'motion_ownership:\n' + '\n'.join(f'{s} — {name}: {RULE}.' for s,name in BINDINGS.items())
    source += '\n\nvisual_attention_timeline:\nKeep the established view.'
    requirement = {'requirement':'Keep all Subjects in their established places.', 'source_excerpt':RULE}
    return source, requirement, {'subject_bindings':BINDINGS, 'dialogue_events':[]}


@pytest.mark.parametrize('group',['all Subjects','all three Subjects','all 3 Subjects'])
def test_collective_motion_keeps_every_owned_location_without_unique_span(case, group):
    text, requirement, authority = case
    requirement['requirement'] = f'Keep {group} in their established places.'
    before = copy.deepcopy(case)
    result = resolve_canonical_excerpt(text, requirement, authority)
    assert result['status'] == 'RESOLVED'
    assert result['method'] == 'CANONICAL_SUBJECT_LOCATIONS'
    assert result['start'] is None and result['end'] is None
    assert result['subject_ids'] == list(BINDINGS)
    assert all(text[x['start']:x['end']] == RULE and x['selected'] for x in result['locations'])
    assert result['semantic_review_required'] and case == before


@pytest.mark.parametrize('change',[
    'wrong_name','wrong_subject','duplicate_subject','missing_actor','different_rule',
    'negation_omitted','partial_clause','wrong_section','extra_scope','wrong_count',
    'actor_exception','unscoped_requirement','explicit_wrong_actor',
])
def test_collective_resolution_never_promotes_wrong_ownership_or_partial_text(case, change):
    text, requirement, authority = case
    if change == 'wrong_name':text = text.replace('<Subject 2> — 乙', '<Subject 2> — 甲')
    elif change == 'wrong_subject':text = text.replace('<Subject 2>', '<Subject 9>')
    elif change == 'duplicate_subject':text = text.replace('<Subject 2> — 乙', '<Subject 1> — 甲')
    elif change == 'missing_actor':text = text.replace(f'<Subject 2> — 乙: {RULE}.\n', '')
    elif change == 'different_rule':text = text.replace(f'<Subject 2> — 乙: {RULE}.', '<Subject 2> — 乙: TRANSLATIONAL_MOTION; walks forward.')
    elif change == 'negation_omitted':text = text.replace(RULE + '.', 'Not ' + RULE + '.', 1)
    elif change == 'partial_clause':requirement['source_excerpt'] = 'SPATIALLY_ANCHORED'
    elif change == 'wrong_section':text = text.replace('motion_ownership:', 'other_scope:')
    elif change == 'extra_scope':text += '\n' + RULE
    elif change == 'wrong_count':requirement['requirement'] = 'Keep all four Subjects in place.'
    elif change == 'actor_exception':requirement['requirement'] = 'Keep all Subjects except <Subject 2> in place.'
    elif change == 'unscoped_requirement':requirement['requirement'] = 'Keep <Subject 1> in place.'
    elif change == 'explicit_wrong_actor':requirement['requirement'] = 'Keep all Subjects, <Subject 9>, in place.'
    result = resolve_canonical_excerpt(text, requirement, authority)
    assert result['status'] != 'RESOLVED'
    assert all(text[x['start']:x['end']] == requirement['source_excerpt'] for x in result['locations'])
