"""Saved C3 remains blocked on its real model-owned Anchor ID error."""
import copy
import json
from pathlib import Path

import pytest

from app.services import h3_execution_optimizer as opt
from app.services.h3_anchor_policy import anchor_policy

FIXTURES = Path(__file__).parent / 'fixtures'


def sample():
    return json.loads((FIXTURES / 'h3_v5_c3_anchor_catalog.json').read_text())


def reparse(s):
    # Derived canonical metadata only. Do not change output/authority_echo.
    authority, initial = copy.deepcopy(s['authority']), copy.deepcopy(s['initial'])
    authority['visual_anchor_order'] = opt.anchor_facts(s['raw_prompt'])
    initial['visual_anchors'] = opt.anchor_declarations(s['raw_prompt'])
    authority['anchor_policy'] = anchor_policy(authority, initial, s['execution_context'])
    return authority, initial


def audit(s):
    authority, initial = reparse(s)
    return opt.check_authority(s['raw_prompt'], s['output'], authority, initial, s['limits'])


def test_saved_c3_scope_resolves_but_picture_id_is_not_repaired_to_kf4():
    s = sample(); before = copy.deepcopy(s)
    authority, initial = reparse(s)
    anchor, = authority['anchor_policy']['catalog']
    reference = s['reference_manifest']['references'][0]
    assert reference['slot'] == 1 and reference['source_keyframe_index'] == 4
    assert anchor['anchor_id'] == 'KF4' and anchor['source_picture'] == '<Picture 1>'
    assert anchor['original_time'] == initial['visual_anchors'][0]['time'] == 10.95
    assert anchor['role'] == 'INTERMEDIATE | Clip-local'
    assert '坐在高背宝座前缘' in anchor['visual_reference_description']
    assert s['output']['av_timeline']['anchors'][0]['id'] == '<Picture 1>'
    result = audit(s)
    assert result['checks']['reference_authority_scope']
    assert not result['checks']['anchor_decisions_complete'] and not result['passed']
    assert result['checks']['stable_speaker_ids'] and result['checks']['execution_budget_explained']
    assert result['checks']['continuation_new_speech_budget']
    assert s == before


@pytest.mark.parametrize('phrase', [
    'previous-video', 'previous video', 'previous  video', 'previous - video',
    'previous\tvideo', 'previous\u00a0video', 'previous\u2010video', 'previous\u2011video',
    'preceding-video', 'preceding video', 'preceding-footage', 'incoming-video',
])
def test_continuation_aliases_are_read_only_and_do_not_bypass_anchor_failure(phrase):
    s = sample()
    s['output']['optimized_prompt'] = s['output']['optimized_prompt'].replace('previous-video', phrase)
    before = copy.deepcopy(s)
    result = audit(s)
    assert result['checks']['reference_authority_scope']
    assert not result['checks']['anchor_decisions_complete'] and not result['passed']
    assert s == before


@pytest.mark.parametrize('verified', [None, False])
@pytest.mark.parametrize('phrase', ['previous-video', 'previous video', 'previous - video', 'preceding-footage'])
def test_aliases_never_supply_standard_or_unverified_reference_authority(verified, phrase):
    s = sample()
    if verified is None:
        s['authority'].pop('continuation')
    else:
        s['authority']['continuation']['binding_verified'] = verified
    s['output']['optimized_prompt'] = s['output']['optimized_prompt'].replace('previous-video', phrase)
    assert not audit(s)['checks']['reference_authority_scope']


@pytest.mark.parametrize('case,check', [
    ('identity_rebound', 'picture_binding_<Picture 3>'),
    ('wrong_role', 'reference_role_<Picture 3>'),
    ('manifest_rebound', 'canonical_manifest_subject_consistent'),
])
def test_real_reference_authority_conflicts_still_fail(case, check):
    s = sample()
    if case == 'identity_rebound':
        s['output']['optimized_prompt'] = s['output']['optimized_prompt'].replace(
            '<Picture 3> supplies identity only for <Subject 1>.',
            '<Picture 3> supplies identity only for <Subject 3>.')
    elif case == 'wrong_role':
        s['output']['optimized_prompt'] += '\n<Picture 3> is SCENE.'
    else:
        s['authority']['reference_bindings'][2]['subject'] = '<Subject 3>'
    result = audit(s)
    assert result['checks']['reference_authority_scope']
    assert not result['checks'][check] and not result['passed']


@pytest.mark.parametrize('delimiter', ['|', '—', ':', '@', '-'])
def test_multiple_anchors_keep_ids_times_picture_bindings_and_exact_visual_semantics(delimiter):
    prompt = '\n'.join([
        f'KF4 {delimiter} INTERMEDIATE {delimiter} Clip-local 10.95s {delimiter} <Picture 1>: seated emperor.',
        f'- KF8 {delimiter} END {delimiter} Clip-local 15.0s {delimiter} <Picture 2>: empty hands.',
    ])
    declarations = opt.anchor_declarations(prompt)
    assert declarations == [{'id': 'KF4', 'time': 10.95, 'picture': '<Picture 1>'},
                            {'id': 'KF8', 'time': 15.0, 'picture': '<Picture 2>'}]
    facts = opt.anchor_facts(prompt)
    authority = {'reference_bindings': [
        {'picture': f'<Picture {i}>', 'state_index': k, 'type': 'DIRECTOR_VISUAL_ANCHOR'}
        for i, k in [(1, 4), (2, 8)]], 'visual_anchor_order': facts}
    catalog = anchor_policy(authority, {'visual_anchors': declarations}, {})['catalog']
    assert [a['anchor_id'] for a in catalog] == ['KF4', 'KF8']
    assert facts[0]['visual_target'] == f'{delimiter} <Picture 1>: seated emperor.'
    assert facts[1]['visual_target'] == f'{delimiter} <Picture 2>: empty hands.'
    assert opt.temporal_declarations(prompt, [{'anchor_id': 'T8', 'source': {'keyframe_index': 8}}]) == [
        {'anchor_id': 'T8', 'time_seconds': 15.0}]
    assert opt._temporal_target_suffix(prompt, 'KF8') == facts[1]['visual_target']


def test_no_anchor_does_not_invent_kf_from_picture_number():
    prompt = 'Picture references: <Picture 4> supplies scene guidance.\nNo explicit keyframe declaration.'
    assert opt.anchor_declarations(prompt) == opt.anchor_facts(prompt) == []
    authority = {'reference_bindings': [{'picture': '<Picture 4>', 'type': 'SCENE'}], 'visual_anchor_order': []}
    assert anchor_policy(authority, {'visual_anchors': []}, {})['catalog'] == []


@pytest.mark.parametrize('conflict', ['wrong_state', 'wrong_picture', 'duplicate_picture', 'duplicate_anchor', 'wrong_kind'])
def test_anchor_catalog_refuses_conflicting_manifest(conflict):
    s = sample()
    reference = s['authority']['reference_bindings'][0]
    if conflict == 'wrong_state': reference['state_index'] = 1
    elif conflict == 'wrong_picture': reference['picture'] = '<Picture 99>'
    elif conflict == 'duplicate_picture': s['authority']['reference_bindings'].append(copy.deepcopy(reference))
    elif conflict == 'duplicate_anchor':
        s['raw_prompt'] += '\nKF4 | END | Clip-local 13s | <Picture 1>: another declaration.'
    else: reference['type'] = 'CHARACTER_IDENTITY'
    with pytest.raises(ValueError, match='H3_ANCHOR_CATALOG_MISMATCH'):
        reparse(s)


@pytest.mark.parametrize('name', ['approved_c1', 'c2_repeated_provenance'])
def test_saved_approved_c1_c2_still_pass_without_modification(name):
    s = json.loads((FIXTURES / f'h3_v5_{name}.json').read_text()); before = copy.deepcopy(s)
    result = opt.check_authority(s['raw_prompt'], s['output'], s['authority'], s['initial'], s['limits'])
    assert result['passed'], result['blocking_findings']
    assert s == before
