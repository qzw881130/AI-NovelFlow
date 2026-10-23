"""Shot18 C3's real carry-only continuation, with no external generation."""
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
from app.services.h3_native_prompt import dialogue_events, speaker_bindings
from app.services.shot_video_service import _semantic_clip_prompt_context
from app.services.video_director_ai import build_h3_video_prompt
from app.utils.path_utils import url_to_local_path
from test_h3_phase_b_single_owned_state import offline_only, FakeDirector, rehash

FIXTURE = Path(__file__).parent / 'fixtures/h3_multi_keyframe_phase_b/test3_shot18_c3_zero_owned.json'


def make_case(db, *, silent=False, policy='AUTO'):
    saved = json.loads(FIXTURE.read_text())
    plan = deepcopy(saved['plan'])
    if silent:
        plan['dialogue_timeline_source'] = []
        for clip in plan['clip_plan']:
            clip['dialogue_assignment'] = []
    novel = Novel(title='offline carry-only test')
    db.add(novel); db.flush()
    chapter = Chapter(novel_id=novel.id, title='offline', number=1)
    db.add(chapter); db.flush()
    shot = Shot(**{k: v for k, v in saved['shot'].items() if k not in {'id', 'chapter_id'}},
                chapter_id=chapter.id, video_director_plan=json.dumps(plan, ensure_ascii=False))
    db.add(shot)
    db.add_all([Prop(novel_id=novel.id, **p) for p in saved['props']])
    db.add(PromptTemplate(name='Offline Phase B', type=pipe.TEMPLATE_TYPE, is_system=True,
                         is_active=True, template=compiler.PHASE_B_TEMPLATE.read_text()))
    db.flush()
    from app.services.effective_execution import project_effective_execution, projection_record
    projection = projection_record(project_effective_execution(plan, plan['clip_plan'][2], policy))
    metadata = {'clip_index': 3, 'continuation_mode': policy, 'execution_projection': projection,
                'capability': 'EXTEND', 'h3_prompt_pipeline': 'phase_b', 'execution_scope': 'CLIP'}
    context = _semantic_clip_prompt_context(plan, metadata,
                                          resolved_dialogue_timeline=plan['dialogue_timeline_source'])
    manifest, contract = deepcopy(saved['manifest']), deepcopy(saved['execution_contract'])
    contract['execution_projection'] = projection
    workflow = SimpleNamespace(**saved['workflow'])
    builder = asyncio.run(build_h3_video_prompt(
        db=db, novel=novel, shot=shot, selected_mode='MULTI_KEYFRAME', clip=context['clip'],
        workflow_capability={}, workflow_type=workflow.type, workflow_name=workflow.name,
        start_image_url=None, keyframes=context['keyframes'], transitions=context['transitions'],
        clip_dialogues=context['clip_dialogues'], reference_images=[],
        character_appearances=saved['character_appearances'], temporal_anchors=[],
        video_reference_manifest=manifest, previous_av_present=True,
        current_visual_state=next(s for s in plan['keyframes'] if s['index'] == 5),
        resolved_dialogue_timeline=plan['dialogue_timeline_source'], input_only=True))
    previous = url_to_local_path(contract['previous_clip']['result_url'])
    snapshot = pipe.runtime_snapshot(plan=plan, builder_input=builder, manifest=manifest, workflow=workflow,
        previous_path=previous, execution_contract=contract, shot_description=shot.description)
    task = Task(type='shot_video', name='Offline C3', status='running', novel_id=novel.id,
                chapter_id=chapter.id, shot_id=shot.id,
                metadata_json=json.dumps({**metadata, 'execution_contract': contract}))
    db.add(task); db.commit()
    args = dict(db=db, task=task, novel=novel, shot=shot, builder_input=builder, manifest=manifest,
                workflow=workflow, previous_path=previous, execution_contract=contract)
    return saved, snapshot, args


def mock_response(prepared):
    events, cursor = [], 1.8
    for fact in prepared['canonical']:
        events.append({'id': fact['id'], 'start': round(cursor, 3)})
        cursor += fact['duration'] + 0.1
    return {'optimized_duration': round(max(cursor + 0.3, 8), 3),
            'dialogue_events': events, 'anchors': [],
            'detailed_description': '<Subject 1>延续端坐与交谈，<Subject 2>自然回应；'
                '摄影机延续既有侧面轴线，只推进当前范围内的动作，不提前达到后续起身状态。' + ''.join(
                    f'[[SPEECH_{i}]]' for i in range(1, len(events) + 1)),
            'overall_soundscape': '大厅环境声与当前动作对应的衣料声。'}


@pytest.mark.parametrize('policy', ['AUTO', 'EXTEND_ONLY'])
@pytest.mark.parametrize('silent', [False, True], ids=['real-dialogue', 'synthetic-silent'])
def test_real_c3_prepare_director_compile_preflight(db_session, policy, silent):
    saved, snapshot, args = make_case(db_session, silent=silent, policy=policy)
    before = deepcopy(snapshot)
    prepared = compiler.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
    assert prepared['status'] == 'PREPARED', prepared
    c = prepared['llm_input']['canonical']
    assert c['owned_visual_states'] == []
    assert c['carry_in_visual_state']['index'] == 5
    assert len(c['transitions']) == 1
    transition = c['transitions'][0]
    assert transition['from_keyframe_index'] == 5 and transition['to_keyframe_index'] == 6
    assert transition['target_state_owned'] is False
    assert transition['projection_mode'] == 'CROSS_CLIP_CONTINUATION'
    assert (transition['clip_local_start_time'], transition['clip_local_end_time']) == (0, 14.95)
    assert 'unowned endpoint' in transition['execution_scope']
    assert prepared['llm_input']['anchor_catalog'] == []
    assert prepared['temporal_anchors'] == []
    assert [r['kind'] for r in prepared['picture_mapping']] == ['SCENE', 'CHARACTER_IDENTITY', 'CHARACTER_IDENTITY']
    assert prepared['continuation']['source_sha256'] == saved['execution_contract']['previous_clip']['physical_output']['sha256']
    assert prepared['continuation']['overlap_seconds'] == 1.625
    assert len(prepared['llm_input']['previous_av']['preview_frames']) == 5
    assert [e['id'] for e in prepared['canonical']] == ([] if silent else ['D10', 'D11', 'D12', 'D13', 'D14', 'D15'])
    llm = FakeDirector(mock_response(prepared))
    prompt = asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    record = json.loads(args['task'].metadata_json)['h3_phase_b']
    assert record['status'] == 'COMPILED' and record['preflight']['passed']
    assert len(llm.calls) == 1
    assert record['director_input']['canonical'] == c
    result = record['compiler_result']
    assert result['execution_decisions']['anchor_decisions'] == []
    assert result['temporal_manifest']['anchors'] == []
    assert result['picture_mapping'] == prepared['picture_mapping']
    bindings = speaker_bindings(prepared['canonical'])
    assert [(e['speaker'], e['speaker_id'], e['exact_dialogue']) for e in dialogue_events(prompt)] == [
        (e['speaker'], bindings[e['speaker']], e['exact_dialogue']) for e in prepared['canonical']]
    for event, fact in zip(result['execution_decisions']['timing']['dialogue_events'], prepared['canonical']):
        assert event['optimized_end'] - event['optimized_start'] == pytest.approx(fact['duration'])
    if silent:
        assert 'All characters remain silent' in prompt
    paths = [r['local_path'] for r in snapshot['reference_manifest']['references']]
    applied = pipe.apply_execution(args['task'], 14.95, args['manifest'], paths)
    assert applied[3] == paths
    assert snapshot == before  # Carry-in stays context; no fabricated owned state.


@pytest.mark.parametrize('change', ['missing_carry', 'missing_transition', 'wrong_carry',
    'omitted_owned', 'generate', 'cut', 'temporal', 'missing_previous', 'changed_previous'])
def test_zero_owned_rejects_invalid_scope_and_dependencies(db_session, change):
    _, snapshot, _ = make_case(db_session)
    plan, builder = snapshot['canonical_plan'], snapshot['builder_input']
    clip = plan['clip_plan'][2]
    # Remove the policy wrapper only in malformed fixtures, so tests reach the
    # underlying input authority checks rather than a policy mismatch first.
    snapshot['physical_evidence'].pop('execution_projection', None)
    if change == 'missing_carry': clip['carry_in_state_index'] = builder['clip']['carry_in_state_index'] = None
    elif change == 'missing_transition': plan['transitions'] = []
    elif change == 'wrong_carry': clip['carry_in_state_index'] = builder['clip']['carry_in_state_index'] = 4
    elif change == 'omitted_owned': plan['keyframes'][5]['time_seconds'] = 30
    elif change == 'generate': clip['capability'] = builder['clip']['capability'] = 'GENERATE'
    elif change == 'cut': clip['continuity_to_previous'] = 'CUT'
    elif change == 'temporal': clip['capability'] = builder['clip']['capability'] = 'TEMPORAL_EXTEND'
    elif change == 'missing_previous': snapshot['previous_video_path'] = None
    elif change == 'changed_previous': snapshot['physical_evidence']['previous_clip']['physical_output']['sha256'] = 'wrong'
    rehash(snapshot)
    result = compiler.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
    assert result['status'] == 'NOT_COVERED', result


@pytest.mark.parametrize('change', ['invent_anchor', 'unknown_subject', 'speaker', 'missing_slot', 'prefix'])
def test_zero_owned_compiler_keeps_authority_checks(db_session, change):
    _, snapshot, _ = make_case(db_session)
    prepared = compiler.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
    assert prepared['status'] == 'PREPARED', prepared
    response = mock_response(prepared)
    if change == 'invent_anchor': response['anchors'] = [{'id': 'KF5'}]
    elif change == 'unknown_subject': response['detailed_description'] += '<Subject 9>'
    elif change == 'speaker': response['detailed_description'] += '<Subject 1> (S9)'
    elif change == 'missing_slot': response['detailed_description'] = response['detailed_description'].replace('[[SPEECH_1]]', '')
    elif change == 'prefix': response['dialogue_events'][0]['start'] = 0
    assert compiler.compile_multi_keyframe_phase_b(prepared, response)['status'] == 'VALIDATION_FAILED'


def test_preflight_rejects_missing_carry_scope(db_session):
    _, snapshot, _ = make_case(db_session)
    prepared = compiler.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
    result = compiler.compile_multi_keyframe_phase_b(prepared, mock_response(prepared))
    assert pipe.preflight(prepared, result)['passed']
    prepared['llm_input']['canonical']['transitions'] = []
    assert not pipe.preflight(prepared, result)['checks']['canonical_scope_available']
