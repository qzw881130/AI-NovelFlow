"""Real test3 revision1 plans; fake Director, in-memory persistence, no generation.

The failed C2 tasks never saved a Director request. Reconstruct it with the same
production input-only builder, using frozen Canonical plans and task manifests.
Original media is only hashed/probed; preview encoding is stubbed out.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.novel import Novel, Chapter, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.models.prompt_template import PromptTemplate
from app.services import h3_phase_b_pipeline as pipe
from app.services import h3_single_stage_experiment as compiler
from app.services.h3_native_prompt import dialogue_events, sections, speaker_bindings
from app.services.shot_video_service import _semantic_clip_prompt_context
from app.services.video_director_ai import build_h3_video_prompt
from app.utils.path_utils import url_to_local_path

ROOT = Path(__file__).parent / 'fixtures/h3_multi_keyframe_phase_b'


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('No external LLM, ComfyUI, or repair stage is allowed')
    from app.services.llm_service import LLMService
    from app.services.comfyui.client import ComfyUIClient
    monkeypatch.setattr(LLMService, 'chat_completion', forbidden)
    for method in ('queue_prompt', 'upload_image', 'upload_video'):
        monkeypatch.setattr(ComfyUIClient, method, forbidden)
    monkeypatch.setattr('app.services.h3_execution_optimizer.optimize_h3_execution_prompt', forbidden)
    monkeypatch.setattr('app.services.h3_preflight_repair.repair_output', forbidden)

    def previews(manifest, temporal, previous_path, continuation):
        # Only the image encoding boundary is fake; actual resource hashes and
        # Previous AV workflow/provenance/frame checks still run in production.
        visual = [{'id': f"Picture:{r['slot']}", 'type': r['kind']}
                  for r in manifest['references']]
        visual += [{'id': a['anchor_id'], 'type': 'TEMPORAL_ANCHOR'} for a in temporal]
        images = [{'url': 'data:image/png;base64,OFFLINE_STUB'} for _ in visual]
        if continuation:
            for i in range(5):
                frame = continuation['source_start_frame'] + round(i * (continuation['context_frames'] - 1) / 4)
                images.append({'url': 'data:image/png;base64,OFFLINE_STUB', 'source_frame_index': frame,
                               'time': frame / continuation['fps']})
                visual.append({'id': f'previous:{i}', 'type': 'PREVIOUS_VIDEO_FRAME'})
        return images, visual
    monkeypatch.setattr(compiler, '_visual_previews', previews)


def make_case(db, shot_number, *, silent=False):
    saved = json.loads((ROOT / f'test3_shot{shot_number}_c2_single_owned.json').read_text())
    plan = deepcopy(saved['plan'])
    if silent:
        # Explicit synthetic variant, never written to the production snapshot.
        plan['dialogue_timeline_source'] = []
        for clip in plan['clip_plan']:
            clip['dialogue_assignment'] = []
    novel = Novel(title='offline single-owned test')
    db.add(novel); db.flush()
    chapter = Chapter(novel_id=novel.id, title='offline', number=1)
    db.add(chapter); db.flush()
    shot = Shot(**{k: v for k, v in saved['shot'].items() if k not in {'id', 'chapter_id'}},
                chapter_id=chapter.id, video_director_plan=json.dumps(plan, ensure_ascii=False))
    db.add(shot)
    db.add_all([Prop(novel_id=novel.id, **p) for p in saved['props']])
    template = PromptTemplate(name='Offline Phase B', type=pipe.TEMPLATE_TYPE, is_active=True,
                              is_system=True, template=compiler.PHASE_B_TEMPLATE.read_text())
    db.add(template); db.flush()
    context = _semantic_clip_prompt_context(plan, {'clip_index': 2},
                                            resolved_dialogue_timeline=plan['dialogue_timeline_source'])
    contract, manifest = deepcopy(saved['execution_contract']), deepcopy(saved['manifest'])
    temporal = (contract.get('temporal_anchor_manifest') or {}).get('anchors', [])
    workflow = SimpleNamespace(**saved['workflow'])
    builder = asyncio.run(build_h3_video_prompt(
        db=db, novel=novel, shot=shot, selected_mode='MULTI_KEYFRAME', clip=context['clip'],
        workflow_capability={}, workflow_type=workflow.type, workflow_name=workflow.name,
        start_image_url=None, keyframes=context['keyframes'], transitions=context['transitions'],
        clip_dialogues=context['clip_dialogues'], reference_images=[],
        character_appearances=saved['character_appearances'], temporal_anchors=temporal,
        video_reference_manifest=manifest, previous_av_present=True,
        current_visual_state=next(s for s in plan['keyframes'] if s['index'] == 2),
        resolved_dialogue_timeline=plan['dialogue_timeline_source'], input_only=True))
    previous = url_to_local_path(contract['previous_clip']['result_url'])
    snapshot = pipe.runtime_snapshot(plan=plan, builder_input=builder, manifest=manifest, workflow=workflow,
        previous_path=previous, execution_contract=contract, shot_description=shot.description)
    task = Task(type='shot_video', name='Offline C2', status='running', novel_id=novel.id,
        chapter_id=chapter.id, shot_id=shot.id, metadata_json=json.dumps({
            'h3_prompt_pipeline': 'phase_b', 'execution_scope': 'CLIP', 'clip_index': 2,
            'capability': context['clip']['capability'], 'execution_contract': contract}))
    db.add(task); db.commit()
    args = dict(db=db, task=task, novel=novel, shot=shot, builder_input=builder, manifest=manifest,
                workflow=workflow, previous_path=previous, execution_contract=contract)
    return saved, snapshot, args


def mock_decisions(prepared, decision='KEEP'):
    """Test decisions only: exercise times, slots and aliases, not director quality."""
    shot_number = prepared['llm_input']['shot']['index']
    # Deliberately different from a Story+overlap transformation. Compiler must
    # honor these explicit Generation Local decisions without adding overlap.
    starts = {1: [1.9], 2: [1.9, 7.4, 10.4]}[shot_number]
    arrival = prepared['llm_input']['anchor_catalog'][0]['original_time']
    if decision == 'RETIME':
        arrival += 0.4
    relation = ({'dialogue_id': prepared['canonical'][0]['id'], 'position': 'DURING'}
                if prepared['canonical'] else None)
    return {
        'optimized_duration': 13.5,
        'dialogue_events': [{'id': c['id'], 'start': start} for c, start in zip(prepared['canonical'], starts)],
        'anchors': [{'id': a['anchor_id'], 'decision': decision,
                     'optimized_time': None if decision == 'DROP' else arrival,
                     'arrival_relation': None if decision == 'DROP' else relation,
                     'reason': 'Offline contract test; Canonical facts and transition scope remain intact.'}
                    for a in prepared['llm_input']['anchor_catalog']],
        'detailed_description': '<Subject 1>延续前片段姿态，完成当前范围内的动作并达到目标状态；'
            '下一过渡仅执行本片段允许的开端。' + ''.join(
                f'[[SPEECH_{i}]]' for i in range(1, len(prepared['canonical']) + 1)),
        'overall_soundscape': '<Subject 1>动作对应的衣料声及场景环境声。',
    }


class FakeDirector:
    def __init__(self, response):
        self.response, self.calls = response, []

    async def chat_completion(self, **request):
        self.calls.append(request)
        return {'success': True, 'content': json.dumps(self.response, ensure_ascii=False)}


@pytest.mark.parametrize('shot_number,refs,dialogues,capability', [
    (1, 6, ['D3'], 'EXTEND'), (2, 9, ['D4', 'D5', 'D6'], 'TEMPORAL_EXTEND')])
@pytest.mark.parametrize('silent', [False, True], ids=['real-dialogue', 'synthetic-silent'])
@pytest.mark.parametrize('decision', ['KEEP', 'RETIME', 'DROP'])
def test_real_c2_prepare_director_compile_preflight(db_session, shot_number, refs, dialogues, capability, silent, decision):
    saved, snapshot, args = make_case(db_session, shot_number, silent=silent)
    before = deepcopy(snapshot)
    p = compiler.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
    assert p['status'] == 'PREPARED', p
    assert snapshot == before
    canonical = p['llm_input']['canonical']
    assert [s['index'] for s in canonical['owned_visual_states']] == [3]
    assert canonical['carry_in_visual_state']['index'] == 2
    assert canonical['owned_visual_states'][0]['description'] == saved['plan']['keyframes'][2]['description']
    assert canonical['carry_in_visual_state']['description'] == saved['plan']['keyframes'][1]['description']
    assert [t['segment_index'] for t in canonical['transitions']] == [2, 3]
    assert [t['projection_mode'] for t in canonical['transitions']] == ['CROSS_CLIP_CONTINUATION', 'CROSS_CLIP_OPENING']
    assert canonical['transitions'][-1]['target_state_owned'] is False
    expected_transitions = _semantic_clip_prompt_context(saved['plan'], {'clip_index': 2})['transitions']
    assert canonical['transitions'] == expected_transitions
    assert [d['id'] for d in p['canonical']] == ([] if silent else dialogues)
    assert p['llm_input']['clip']['capability'] == capability
    assert p['llm_input']['execution_budget']['story_duration'] == pytest.approx(9.4 if shot_number == 1 else 11.1)
    assert p['continuation']['source_sha256'] == saved['execution_contract']['previous_clip']['physical_output']['sha256']
    assert p['continuation']['overlap_seconds'] == 1.625
    assert len(p['llm_input']['previous_av']['preview_frames']) == 5
    assert len(p['picture_mapping']) == refs
    assert [a['anchor_id'] for a in p['llm_input']['anchor_catalog']] == (
        ['KF3'] if shot_number == 1 else ['KF3', 'clip-2-KF3'])
    assert p['llm_input']['anchor_catalog'][0]['source_picture'] is None
    # Real C2 manifests put identity images in a different order from Subjects.
    bindings = snapshot['builder_input']['reference_binding_contract']['characters']
    assert [b['name'] for b in bindings] != snapshot['builder_input']['clip_visible_characters']
    assert p['subject_names'] == {b['subject']: b['name'] for b in bindings}
    assert list(p['subject_names'].values()) == snapshot['builder_input']['clip_visible_characters']
    if not silent:
        assert [e['speaker'] for e in p['canonical']] == (
            ['<Subject 3>'] if shot_number == 1 else ['<Subject 4>', '<Subject 2>', '<Subject 1>'])
    for ref in snapshot['reference_manifest']['references']:
        assert p['resource_hashes'][f"<Picture {ref['slot']}>"] == saved['resource_hashes'][ref['local_path']]

    response = mock_decisions(p, decision)
    llm = FakeDirector(response)
    prompt = asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    db_session.expire(args['task'])
    record = json.loads(args['task'].metadata_json)['h3_phase_b']
    result = record['compiler_result']
    assert record['status'] == 'COMPILED'
    assert record['version'] == record['preflight']['contract'] == 'H3_PHASE_B_LIMITED_V3'
    assert record['preflight']['passed'] and all(record['preflight']['checks'].values())
    assert len(llm.calls) == record['llm_call_count'] == 1
    assert json.loads(llm.calls[0]['user_content'])['canonical'] == canonical
    assert record['director_input']['canonical'] == canonical  # DROP does not delete story facts.
    assert '[[SPEECH_' not in prompt
    events = dialogue_events(prompt)
    assert [(e['speaker'], e['exact_dialogue']) for e in events] == [
        (c['speaker'], c['exact_dialogue']) for c in p['canonical']]
    assert p['llm_input']['speaker_bindings'] == speaker_bindings(p['canonical'])
    timing = result['execution_decisions']['timing']
    for event, chosen, fact in zip(timing['dialogue_events'], response['dialogue_events'], p['canonical']):
        assert event['optimized_start'] == chosen['start']
        assert event['optimized_end'] == pytest.approx(chosen['start'] + fact['duration'])
    assert result['picture_mapping'] == p['picture_mapping']
    assert '<Subject 1>' in sections(prompt)['detailed_description']
    if silent:
        assert 'All characters remain silent' in prompt and '<d>' not in prompt
        assert p['llm_input']['speaker_bindings'] == {} and p['llm_input']['speech_slots'] == []
    paths = [r['local_path'] for r in snapshot['reference_manifest']['references']]
    applied = pipe.apply_execution(args['task'], snapshot['builder_input']['clip']['planned_duration'], args['manifest'], paths)
    assert applied[0] == response['optimized_duration']
    assert applied[3] == paths
    temporal = result['temporal_manifest']['anchors']
    assert len(temporal) == int(shot_number == 2 and decision != 'DROP')
    if temporal:
        assert temporal[0]['source']['keyframe_index'] == 3
        assert temporal[0]['time_seconds'] == response['anchors'][0]['optimized_time']
        assert temporal[0]['image_url'] == saved['execution_contract']['temporal_anchor_manifest']['anchors'][0]['image_url']
        # Compiler exports temporal decisions; apply_execution restores the
        # frozen physical path from the original execution contract.
        bound = applied[1]['anchors'][0]
        assert bound['local_path'] == saved['execution_contract']['temporal_anchor_manifest']['anchors'][0]['local_path']
        assert p['resource_hashes']['TemporalAnchor:clip-2-KF3'] == saved['resource_hashes'][bound['local_path']]
    assert snapshot == before


def rehash(snapshot):
    for key in snapshot['source']['hashes']:
        snapshot['source']['hashes'][key] = compiler._snapshot_digest(snapshot[key])


@pytest.mark.parametrize('change,error', [
    ('zero_owned', 'OWNED_VISUAL_STATE_REQUIRED'), ('unknown_owned', 'KeyError: 999'),
    ('unknown_carry', 'KeyError: 999'), ('carry_as_owned', 'SAVED_CLIP_MISMATCH'),
    ('carry_changed', 'SAVED_CLIP_MISMATCH'), ('state_description', 'SAVED_STATES_MISMATCH'),
    ('state_time', 'SAVED_STATES_MISMATCH'), ('missing_previous', 'PREVIOUS_AV_BINDING_MISSING'),
    ('identity_picture', 'IDENTITY_PICTURE_BINDING_MISMATCH'),
    ('subject_swap', 'UPSTREAM_SUBJECT_BINDING_AMBIGUOUS'),
    ('subject_duplicate', 'UPSTREAM_SUBJECT_BINDING_AMBIGUOUS'),
    ('missing_temporal', 'TEMPORAL_MANIFEST_UNVERIFIED'),
])
def test_single_state_does_not_relax_input_authority(db_session, change, error):
    _, snapshot, _ = make_case(db_session, 2)
    clip = snapshot['canonical_plan']['clip_plan'][1]
    builder = snapshot['builder_input']
    if change == 'zero_owned':
        clip['visual_state_indexes'] = builder['clip']['visual_state_indexes'] = []
        builder['visual_controls'] = []
    elif change == 'unknown_owned':
        clip['visual_state_indexes'] = builder['clip']['visual_state_indexes'] = [999]
    elif change == 'unknown_carry':
        clip['carry_in_state_index'] = builder['clip']['carry_in_state_index'] = 999
    elif change == 'carry_as_owned': builder['clip']['visual_state_indexes'] = [2, 3]
    elif change == 'carry_changed': builder['clip']['carry_in_state_index'] = 1
    elif change == 'state_description': builder['visual_controls'][0]['description'] = 'changed'
    elif change == 'state_time': builder['visual_controls'][0]['time_seconds'] += 1
    elif change == 'missing_previous': snapshot['previous_video_path'] = None
    elif change == 'identity_picture': builder['reference_binding_contract']['characters'][0]['picture'] = '<Picture 9>'
    elif change == 'subject_swap':
        a, b = builder['reference_binding_contract']['characters'][:2]
        a['subject'], b['subject'] = b['subject'], a['subject']
    elif change == 'subject_duplicate':
        builder['reference_binding_contract']['characters'][1]['subject'] = builder['reference_binding_contract']['characters'][0]['subject']
    elif change == 'missing_temporal': snapshot['physical_evidence']['temporal_anchors'] = []
    rehash(snapshot)
    result = compiler.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
    assert result['status'] == 'NOT_COVERED' and error in str(result['reasons']), result


@pytest.mark.parametrize('change', ['carry_anchor', 'unknown_subject', 'picture', 'speaker',
    'speech_text', 'missing_slot', 'relation', 'alias', 'shared_prefix'])
def test_single_state_does_not_relax_compiler_preflight(db_session, change):
    _, snapshot, _ = make_case(db_session, 2)
    prepared = compiler.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
    assert prepared['status'] == 'PREPARED', prepared
    response = mock_decisions(prepared)
    if change == 'carry_anchor': response['anchors'][0]['id'] = 'KF2'
    elif change == 'unknown_subject': response['detailed_description'] += '<Subject 999>'
    elif change == 'picture': response['detailed_description'] += '<Picture 99>'
    elif change == 'speaker': response['detailed_description'] += '<Subject 1> (S9)'
    elif change == 'speech_text': response['detailed_description'] += prepared['canonical'][0]['exact_dialogue']
    elif change == 'missing_slot': response['detailed_description'] = response['detailed_description'].replace('[[SPEECH_1]]', '')
    elif change == 'relation': response['anchors'][0]['arrival_relation']['dialogue_id'] = 'D999'
    elif change == 'alias': response['anchors'][1].update(decision='RETIME', optimized_time=5.6)
    elif change == 'shared_prefix': response['dialogue_events'][0]['start'] = 0
    result = compiler.compile_multi_keyframe_phase_b(prepared, response)
    assert result['status'] == 'VALIDATION_FAILED', result
    assert pipe.preflight(prepared, result)['passed'] is False
