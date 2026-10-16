"""Saved Shot17 C1 facts + explicitly offline prose; no model or media calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.services import h3_single_stage_experiment as compiler
from app.services.h3_native_prompt import SECTIONS, dialogue_events, sections, speaker_bindings
from app.services.h3_phase_b_pipeline import preflight


FIXTURE = Path(__file__).parent / 'fixtures/h3_multi_keyframe_phase_b/shot17_c1_subject_references.json'


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Subject reference tests must not call an external stage')
    from app.services.llm_service import LLMService
    from app.services.comfyui.client import ComfyUIClient
    monkeypatch.setattr(LLMService, 'chat_completion', forbidden)
    monkeypatch.setattr(ComfyUIClient, 'queue_prompt', forbidden)
    monkeypatch.setattr(ComfyUIClient, 'upload_image', forbidden)


def shot17_case():
    """Reconstruct Compiler inputs from the saved real prepared-input projection."""
    saved = json.loads(FIXTURE.read_text())
    payload = saved['director_input']
    assigned = payload['canonical']['dialogue_timeline']
    canonical = [dict(id=slot['id'], speaker=slot['speaker'], exact_dialogue=line['text'],
                      duration=slot['fixed_duration'])
                 for slot, line in zip(payload['speech_slots'], assigned)]
    prepared = dict(status='PREPARED', llm_input=payload, canonical=canonical, assigned=assigned,
        subject_names=payload['subject_bindings'], character_appearances=payload['shot']['official_character_appearances'],
        limits=payload['execution_budget']['duration_limits'], continuation=None,
        reference_manifest=payload['reference_manifest'], picture_mapping=payload['picture_mapping'],
        temporal_anchors=[], music_contract=payload['music_policy'],
        drop_capability=payload['reference_selection_capability'],
        authority={'reference_bindings': [{'picture': r['picture'], 'type': r['kind']} for r in payload['picture_mapping']],
                   'anchor_policy': {'catalog': payload['anchor_catalog']}})
    response = {**saved['original_response'], **saved['subject_prose']}
    return prepared, response, saved['original_response']


def test_shot17_subject_prose_preserves_all_authority_and_slots():
    p, response, old = shot17_case()
    before = deepcopy((p, response))
    result = compiler.compile_multi_keyframe_phase_b(p, response)
    historical = compiler.compile_multi_keyframe_phase_b(p, old)
    assert result['status'] == 'CANDIDATE_FOR_REVIEW', result
    assert preflight(p, result)['passed']
    assert (p, response) == before
    assert p['subject_names'] == {'<Subject 1>': '骗子1', '<Subject 2>': '骗子2', '<Subject 3>': '老大臣'}
    assert p['llm_input']['speaker_bindings'] == speaker_bindings(p['canonical'])
    assert result['execution_decisions'] == historical['execution_decisions']
    assert result['picture_mapping'] == historical['picture_mapping'] == p['picture_mapping']
    assert result['reference_manifest'] == historical['reference_manifest']
    assert len(result['picture_mapping']) == 6
    parts = sections(result['prompt'])
    assert list(parts) == list(SECTIONS)
    assert parts['subject_definitions'] == sections(historical['prompt'])['subject_definitions']
    for heading in SECTIONS[1:]:
        assert all(name not in parts[heading] for name in p['subject_names'].values())
    assert 'CHARACTER_IDENTITY for <Subject 3>: stable identity only' in parts['retention_analysis']
    events = dialogue_events(result['prompt'])
    assert len(events) == 7
    assert [(e['speaker'], e['exact_dialogue']) for e in events] == [
        (c['speaker'], c['exact_dialogue']) for c in p['canonical']]
    assert '<Subject 3> (S3) [D3 @ 2.9-6.4s generated-clip] says,' in result['prompt']
    detail = parts['detailed_description']
    for i, e in reversed(list(enumerate(events, 1))):
        detail = detail[:e['span_start']] + f'[[SPEECH_{i}]]' + detail[e['span_end']:]
    assert detail == response['detailed_description']
    assert parts['overall_soundscape'] == response['overall_soundscape']
    assert 'off-screen' not in result['prompt']


def test_old_name_prose_is_compatible_and_not_rewritten():
    p, _, old = shot17_case()
    r = compiler.compile_multi_keyframe_phase_b(p, old)
    assert preflight(p, r)['passed']
    assert r['director_response'] == old
    assert sections(r['prompt'])['overall_soundscape'] == old['overall_soundscape']
    assert '骗子1' in sections(r['prompt'])['detailed_description']


@pytest.mark.parametrize('tag', ['<Subject 99>', '<Subject 0>', '<Subject -1>', '<Subject 01>', '<Subject  1>'])
@pytest.mark.parametrize('field', ['detailed_description', 'overall_soundscape'])
def test_unknown_or_noncanonical_subject_is_rejected(tag, field):
    p, response, _ = shot17_case()
    response[field] += tag
    r = compiler.compile_multi_keyframe_phase_b(p, response)
    assert r['status'] == 'VALIDATION_FAILED'
    assert 'H3_PHASE_B_UNDEFINED_SUBJECT_REFERENCE' in str(r['reasons'])
    assert not preflight(p, r)['passed']


@pytest.mark.parametrize('mutation', ['picture', 'speaker', 'bare_subject', 'definitions',
    'extra_field', 'dialogue_tag', 'dialogue_text', 'slot_missing', 'slot_reordered'])
def test_allowing_subject_does_not_delegate_other_authority(mutation):
    p, response, _ = shot17_case()
    if mutation == 'picture': response['overall_soundscape'] += '<Picture 5>'
    elif mutation == 'speaker': response['detailed_description'] += '<Subject 3> (S1)'
    elif mutation == 'bare_subject': response['detailed_description'] += 'Subject 1'
    elif mutation == 'definitions': response['detailed_description'] += '\nsubject_definitions:\n<Subject 1> is 老大臣'
    elif mutation == 'extra_field': response['subject_definitions'] = {'<Subject 1>': '老大臣'}
    elif mutation == 'dialogue_tag': response['detailed_description'] += '<d>fake</d>'
    elif mutation == 'dialogue_text': response['overall_soundscape'] += p['canonical'][2]['exact_dialogue']
    elif mutation == 'slot_missing': response['detailed_description'] = response['detailed_description'].replace('[[SPEECH_3]]', '')
    elif mutation == 'slot_reordered': response['detailed_description'] = response['detailed_description'].replace('[[SPEECH_3]]', '[[SPEECH_4]]')
    result = compiler.compile_multi_keyframe_phase_b(p, response)
    assert result['status'] == 'VALIDATION_FAILED'
    assert not preflight(p, result)['passed']


def test_no_global_replacement_of_dialogue_resource_names_or_ordinary_words():
    p, response, _ = shot17_case()
    # Deliberate offline variant: a bound name inside spoken words and asset names.
    p['canonical'][0]['exact_dialogue'] = p['assigned'][0]['text'] = '老大臣，请进。'
    p['reference_manifest']['references'][1]['source_name'] = '老大臣的书房'
    p['reference_manifest']['references'][-1]['source_name'] = '老大臣手杖'
    response['detailed_description'] += '<Subject 1>看向老大臣手杖。'
    r = compiler.compile_multi_keyframe_phase_b(p, response)
    assert preflight(p, r)['passed'], r
    assert dialogue_events(r['prompt'])[0]['exact_dialogue'] == '老大臣，请进。'
    assert 'SCENE / 老大臣的书房' in r['prompt'] and 'PROP / 老大臣手杖' in r['prompt']
    assert '<Subject 1>看向老大臣手杖。' in r['prompt']
    assert '<Subject 3> is 老大臣,' in sections(r['prompt'])['subject_definitions']


def test_speaker_number_still_follows_first_speech_not_subject_number():
    p, response, _ = shot17_case()
    p['canonical'][0]['speaker'] = '<Subject 3>'
    p['assigned'][0]['speaker'] = '老大臣'
    r = compiler.compile_multi_keyframe_phase_b(p, response)
    assert preflight(p, r)['passed'], r
    assert '<Subject 3> (S1) [D1 @ 1-2s generated-clip]' in r['prompt']
    assert '<Subject 1> (S3) [D4 @ 6.6-7.85s generated-clip]' in r['prompt']


def test_subject_permission_does_not_change_phase_a_director_only_contract():
    p, response, old = shot17_case()
    r = compiler.compile_multi_keyframe_phase_b(p, old)
    def assemble(prose):
        return compiler.assemble_authority_owned_candidate(
            f"detailed_description:\n{prose['detailed_description']}\n\noverall_soundscape:\n{prose['overall_soundscape']}",
            p['canonical'], r['execution_decisions']['timing'], p['subject_names'], p['picture_mapping'], None,
            'N/A', director_only=True, character_appearances=p['character_appearances'])
    prompt, _, _ = assemble(old)
    assert 'CHARACTER_IDENTITY for <Subject 3> (老大臣)' in prompt
    with pytest.raises(ValueError, match='DIALOGUE_SLOTS_INVALID'):
        assemble(response)
