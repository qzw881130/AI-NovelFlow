"""Exact, ordered, source-scoped fragments; provenance is not semantic approval."""
import copy
import json
from pathlib import Path

import pytest

from app.services.h3_evidence import resolve_canonical_excerpt
from app.services.h3_execution_optimizer import check_authority


def sample():
    return json.loads((Path(__file__).parent / 'fixtures/h3_v5_c3_fragment_provenance.json').read_text())


def audit(s):
    return check_authority(s['raw_prompt'], s['output'], s['authority'], s['initial'], s['limits'])


def test_real_c3_resolves_two_exact_spans_without_mutating_model_or_canonical():
    s = sample(); before = copy.deepcopy(s); result = audit(s)
    assert result['passed'], result['blocking_findings']
    assert len(result['checks']) == 62 and all(result['checks'].values())
    e = result['resolved_evidence']['entries']['requirements.3.source']
    assert e['method'] == 'CANONICAL_ORDERED_SPANS' and e['mismatch']
    assert [(p['start'], p['end']) for p in e['resolved_spans']] == [(68, 125), (166, 182)]
    source = next(x['text'] for x in s['authority']['anchor_policy']['canonical_visual_sources'] if x['id'] == 'transition_1')
    assert e['excerpt'] == source[e['start']:e['end']]
    assert all(source[p['start']:p['end']] == p['excerpt'] for p in e['locations'])
    assert e['supplied_excerpt'] == s['output']['canonical_visual_requirements'][3]['source_excerpt']
    assert result['evidence_provenance']['unresolved'] == []
    assert result['evidence_provenance']['mismatches'] == ['requirements.3.source']
    assert result['semantic_consistency']['status'] == 'REVIEW_REQUIRED'
    assert s == before


@pytest.mark.parametrize('kind', ['wrong_source', 'missing_fragment', 'reversed', 'wrong_actor',
                                 'cross_source', 'wrong_actor_splice', 'substring', 'negation'])
def test_source_problems_still_block_c3(kind):
    s = sample(); req = s['output']['canonical_visual_requirements'][3]
    a, b = req['source_excerpt'].split('；')
    sources = s['authority']['anchor_policy']['canonical_visual_sources']
    source = next(x for x in sources if x['id'] == 'transition_1')
    if kind == 'wrong_source': req['source_id'] = 'transition_2'
    elif kind == 'missing_fragment': req['source_excerpt'] = a + '；两手握住一卷真实布料'
    elif kind == 'reversed': req['source_excerpt'] = b + '；' + a
    elif kind == 'wrong_actor': req['requirement'] = req['requirement'].replace('<Subject 4>', '<Subject 3>')
    elif kind == 'cross_source':
        source['text'] = source['text'].replace(b, '大厅安静')
        next(x for x in sources if x['id'] == 'transition_2')['text'] += '。' + b + '。'
    elif kind == 'wrong_actor_splice':
        req['source_excerpt'] = a + '；宫廷总管始终垂手站在台阶侧方，不改变站位，只将谨慎的视线稳定移向皇帝'
    elif kind == 'substring': req['source_excerpt'] = a + '；不出现实体布料'
    elif kind == 'negation': source['text'] = source['text'].replace(b, '并非' + b)
    before = copy.deepcopy(s); result = audit(s)
    assert not result['passed'] and not result['checks']['canonical_visual_requirement_trace'], kind
    assert s == before


@pytest.mark.parametrize('kind', ['missing_action', 'wrong_actor', 'cloth_created', 'wrong_speaker', 'reordered_dialogue'])
def test_resolved_source_does_not_bypass_independent_final_prompt_checks(kind):
    s = sample(); o = s['output']; action = o['canonical_visual_requirements'][3]['prompt_excerpt']
    if kind == 'missing_action': o['optimized_prompt'] = o['optimized_prompt'].replace(action, '')
    elif kind == 'wrong_actor': o['optimized_prompt'] = o['optimized_prompt'].replace(action, action.replace('<Subject 4>', '<Subject 3>'))
    elif kind == 'cloth_created': o['optimized_prompt'] = o['optimized_prompt'].replace(action, action.replace('remains visibly empty', 'contains real cloth'))
    elif kind == 'wrong_speaker': o['optimized_prompt'] = o['optimized_prompt'].replace('<Subject 4> (S3) says', '<Subject 3> (S2) says')
    elif kind == 'reordered_dialogue':
        p = o['optimized_prompt']; a = '真的有这样的布？'; b = '那么，它真的能分辨愚蠢的人？'
        o['optimized_prompt'] = p.replace(a, '__TEMP__').replace(b, a).replace('__TEMP__', b)
    result = audit(s)
    assert result['checks']['canonical_visual_requirement_trace']
    assert not result['passed'], kind


def resolve(text, quote, description='Preserve <Subject 1> action and empty hands.'):
    return resolve_canonical_excerpt(text, {'source_excerpt': quote, 'requirement': description},
                                     {'subject_bindings': {'<Subject 1>': '甲', '<Subject 2>': '乙'}})


def test_contiguous_quote_keeps_exact_matching():
    text = '<Subject 1> raises empty hands; the hands remain empty.'
    e = resolve(text, text)
    assert e['status'] == 'RESOLVED' and e['method'] == 'EXACT' and not e['mismatch']


def test_unique_ordered_path_keeps_all_real_occurrences():
    text = '<Subject 1> raises empty hands; <Subject 2> watches silently. The palms stay empty. <Subject 1> raises empty hands.'
    e = resolve(text, '<Subject 1> raises empty hands; The palms stay empty.')
    assert e['status'] == 'RESOLVED'
    assert len(e['locations']) == 3 and sum(p['selected'] for p in e['locations']) == 2
    assert all(text[p['start']:p['end']] == p['excerpt'] for p in e['locations'])


@pytest.mark.parametrize('text,quote', [
    ('<Subject 1> raises empty hands; <Subject 2> watches. The palms stay empty. <Subject 1> raises empty hands; <Subject 2> watches. The palms stay empty.', '<Subject 1> raises empty hands; The palms stay empty.'),
    ('D1:\n<Subject 1> raises empty hands.\nD2:\n<Subject 2> watches. The palms stay empty.', '<Subject 1> raises empty hands; The palms stay empty.'),
    ('<Subject 1> raises empty hands.\n\n<Subject 2> watches. The palms stay empty.', '<Subject 1> raises empty hands; The palms stay empty.'),
    ('<Subject 1> raises empty hands; <Subject 2> steps back. He lowers the hands.', '<Subject 1> raises empty hands; He lowers the hands.'),
    ('<Subject 1> raises empty hands; <Subject 2>: The hands stay empty.', '<Subject 1> raises empty hands; The hands stay empty.'),
])
def test_ambiguous_sections_or_implicit_different_owner_never_pass(text, quote):
    assert resolve(text, quote)['status'] != 'RESOLVED'
