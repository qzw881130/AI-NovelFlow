"""Offline replay of the saved Shot 12 C2 #11/#14 Preflight input and output."""
import copy
import json
from pathlib import Path

import pytest

from app.services.h3_execution_optimizer import check_authority


FIXTURE = Path(__file__).parent / 'fixtures/h3_shot12_c2_saved_preflight.json'


def saved_case():
    return json.loads(FIXTURE.read_text())


def audit(case):
    return check_authority(case['raw_prompt'], case['output'], case['authority'],
                           case['initial'], case['limits'])


def source(result, index):
    return result['resolved_evidence']['entries'][f'requirements.{index}.source']


def test_saved_shot12_c2_replay_reattributes_both_quotes_without_mutating_input():
    case = saved_case()
    assert case['task_id'] == '280ca81c-b721-49fc-9c2c-c5bad7823898'
    assert case['llm_log_id'] == '4de3abaa-8a52-49e6-a4dc-5e8d3a12c7e1'
    before = copy.deepcopy(case)
    result = audit(case)
    assert result['passed'] and result['blocking_findings'] == []
    assert len(result['checks']) == 62 and all(result['checks'].values())
    assert case == before
    assert (source(result, 4)['declared_source_id'], source(result, 4)['resolved_source_id']) == (
        'opening_state', 'transition_5')
    assert (source(result, 5)['declared_source_id'], source(result, 5)['resolved_source_id']) == (
        'transition_6', 'transition_6.clip_scope.execution_scope')
    assert source(result, 4)['scope'] == 'canonical_source:transition_5'
    assert source(result, 5)['scope'] == 'clip_scope:transition_6.clip_scope.execution_scope'
    for index in (4, 5):
        entry = source(result, index)
        assert entry['status'] == 'RESOLVED'
        assert entry['resolution_status'] == 'AUTHORIZED_SOURCE_REATTRIBUTED'
        assert entry['mismatch_reason']
        assert entry['source_excerpt'] == case['output']['canonical_visual_requirements'][index]['source_excerpt']
        assert result['resolved_evidence']['entries'][f'requirements.{index}.prompt']['status'] == 'RESOLVED'
    assert {w['requirement_id'] for w in result['warnings']
            if w.get('code') == 'CANONICAL_SOURCE_REATTRIBUTED'} == {'CVR5', 'CVR6'}


def test_correctly_attributed_quote_remains_direct_source():
    result = audit(saved_case())
    entry = source(result, 1)
    assert entry['declared_source_id'] == entry['resolved_source_id'] == 'transition_5'
    assert entry['resolution_status'] == 'DECLARED_SOURCE'
    assert entry['mismatch_reason'] is None


def test_current_clip_source_mislabeled_as_another_source_is_allowed():
    case = saved_case()
    case['output']['canonical_visual_requirements'][4]['source_id'] = 'transition_6'
    result = audit(case)
    assert result['passed']
    assert source(result, 4)['resolved_source_id'] == 'transition_5'


def test_other_clip_source_is_not_in_the_authorized_catalog():
    case = saved_case()
    foreign = '另一 Clip 的独有动作：宫廷总管已经深躬行礼。'
    case['authority']['other_clip_sources'] = [{'id': 'transition_7', 'text': foreign}]
    case['output']['canonical_visual_requirements'][4]['source_excerpt'] = foreign
    result = audit(case)
    assert not result['passed']
    assert 'canonical_visual_requirement_trace' in result['blocking_findings']
    assert source(result, 4)['resolved_source_id'] is None


def test_nonexistent_source_quote_and_ambiguous_current_sources_stay_blocking():
    case = saved_case()
    case['output']['canonical_visual_requirements'][4]['source_excerpt'] = '任何授权来源均不存在的动作。'
    assert 'canonical_visual_requirement_trace' in audit(case)['blocking_findings']
    case = saved_case()
    quote = case['output']['canonical_visual_requirements'][4]['source_excerpt']
    sources = case['authority']['anchor_policy']['canonical_visual_sources']
    next(s for s in sources if s['id'] == 'transition_6')['text'] += quote
    result = audit(case)
    assert not result['passed']
    assert source(result, 4)['resolution_status'] == 'AMBIGUOUS_AUTHORIZED_SOURCE'


def test_unknown_declared_source_id_cannot_borrow_a_current_clip_quote():
    case = saved_case()
    case['output']['canonical_visual_requirements'][4]['source_id'] = 'transition_999'
    result = audit(case)
    assert not result['passed']
    assert 'canonical_visual_requirement_trace' in result['blocking_findings']
    assert source(result, 4)['resolved_source_id'] is None


def test_missing_final_prompt_evidence_does_not_pass_on_source_reattribution():
    case = saved_case()
    excerpt = case['output']['canonical_visual_requirements'][4]['prompt_excerpt']
    case['output']['optimized_prompt'] = case['output']['optimized_prompt'].replace(excerpt, '')
    result = audit(case)
    assert not result['passed']
    assert 'canonical_visual_requirement_consistency' in result['blocking_findings']


def test_explicit_canonical_reblocking_conflict_still_blocks():
    case = saved_case()
    case['output']['optimized_prompt'] = case['output']['optimized_prompt'].replace(
        'overall_soundscape:', '<Subject 1> moves to the opposite side.\n\noverall_soundscape:')
    result = audit(case)
    assert not result['passed']
    assert 'canonical_floor_position_<Subject 1>' in result['blocking_findings']


@pytest.mark.parametrize('kind,check', [
    ('speaker', 'dialogue_timeline_matches_prompt_and_initial'),
    ('dialogue_text', 'dialogue_timeline_matches_prompt_and_initial'),
    ('picture', 'reference_projection_consistent'),
    ('duration', 'duration_within_workflow_and_20s'),
])
def test_independent_authority_violations_still_block(kind, check):
    case = saved_case()
    output = case['output']
    if kind == 'speaker':
        output['av_timeline']['dialogue_events'][0]['speaker'] = '<Subject 4>'
    elif kind == 'dialogue_text':
        output['optimized_prompt'] = output['optimized_prompt'].replace('如果连我都看不见……', '擅自改写的台词')
    elif kind == 'picture':
        output['reference_projection'][0]['picture'] = '<Picture 9>'
    else:
        output['av_timeline']['optimized_duration'] = 30.0
    result = audit(case)
    assert not result['passed']
    assert check in result['blocking_findings']
