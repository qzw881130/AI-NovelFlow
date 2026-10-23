"""Scoped director conclusions, not a detector or a real planning E2E."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import clip_planner as cp
from app.services.clip_execution_compiler import (
    EARLY_COMPOSITION_CONTRACT, TEMPORAL_DECISION_CONTRACT, compile_extend_clip,
    compile_temporal_extend_clip, get_canonical_execution_readiness,
)
from app.services.clip_validator import validate_clip_plan
from app.services.required_visual_state_images import project_required_execution_images
from test_two_stage_temporal_decision import _candidates


def round2():
    return json.loads((Path(__file__).parent / 'fixtures/early_composition_round2.json').read_text())


def inherited(source='KF2', target='KF3', preserved=True):
    return dict(state_id=source, transition_to_state_id=target, premise_preserved=preserved)


def project(data, index, conclusion=None):
    clips = deepcopy(data['raw_clips'])
    cp._project_clip_visual_states(clips, data['visual_state_candidates'])
    clip = clips[index-1]
    clip['inherited_start_composition'] = conclusion
    cp._project_temporal_targets([clip], data['visual_state_candidates'], clips[-1]['end_time'])
    cp._project_early_composition_states([clip], data['visual_state_candidates'],
                                       data['speech_timing_intervals'], data['transition_context'])
    anchors = cp._build_temporal_anchors([clip], data['visual_state_candidates'])
    return clip, anchors


def image_plan(tmp_path, data, clip, anchors):
    main = tmp_path / 'main.png'
    main.write_bytes(b'image')
    plan = dict(canonical_visual_plan=True, clip_plan_revision=1, clip_plan=[clip],
                keyframes=[dict(s, index=s['keyframe_index']) for s in data['visual_state_candidates']],
                temporal_anchors=anchors, clip_plan_validation=dict(passed=True,
                    temporal_contract=TEMPORAL_DECISION_CONTRACT, composition_contract=EARLY_COMPOSITION_CONTRACT))
    shot = SimpleNamespace(id='shot', duration=68, description='scene', image_url=str(main),
                           image_path=str(main), image_task_id=None, keyframes='[]',
                           video_director_plan=json.dumps(plan))
    return shot, plan


def test_round2_c2_inherited_only_has_no_image_or_anchor_and_keeps_previous_provenance(tmp_path):
    data = round2()
    data['raw_clips'][1]['reason'] = 'Audited semantic fixture: KF2 establishes three subjects across the threshold with boxes; adjacent transition preserves axis, positions and props at this opening.'
    clip, anchors = project(data, 2, inherited())
    assert clip['capability'] == 'EXTEND' and clip['requires_temporal_control'] is False
    assert clip['early_composition_state_id'] is None and clip['selected_temporal_target_ids'] == []
    assert clip['carry_in_state_index'] == 2 and clip['visual_state_indexes'] == []
    assert anchors == [] and clip['temporal_anchor_ids'] == []
    shot, plan = image_plan(tmp_path, data, clip, anchors)
    assert project_required_execution_images(shot, plan) == []
    previous = dict(clip_index=1, clip_plan_revision=1, generated_by_task_id='approved-c1',
                    result_url='approved-c1.mp4', physical_output={'physical_output_role': 'CLIP_ONLY'})
    compiled = compile_extend_clip(shot, plan, clip, 1, previous)
    assert compiled['video_reference_manifest']['references'] == []
    assert compiled['execution_contract']['previous_clip']['generated_by_task_id'] == 'approved-c1'
    assert compiled['execution_contract']['previous_clip']['physical_output'] == previous['physical_output']
    assert 'temporal_anchor_manifest' not in compiled['execution_contract']
    assert get_canonical_execution_readiness(shot, plan)['ready']


def test_inherited_with_later_timed_target_projects_only_that_target(tmp_path):
    data = dict(visual_state_candidates=_candidates([
        dict(index=1, role='START', time_seconds=0, timed_visual_target=False),
        dict(index=2, time_seconds=4.8, description='Two subjects facing across a desk; folder on desk.', timed_visual_target=False),
        dict(index=3, time_seconds=8, description='Subject reaches window.', timed_visual_target=True),
    ]), speech_timing_intervals=[dict(start_time=5, end_time=10)],
        transition_context=[dict(from_keyframe_index=2, to_keyframe_index=3, start_time=4.8,
                                end_time=8, transition_description='Preserve desk/axis; later walk to window.')],
        raw_clips=[dict(clip_index=1, start_time=0, end_time=5),
                   dict(clip_index=2, start_time=5, end_time=12, continuity_to_previous='CONTINUOUS',
                        previous_clip_index=1, early_composition_state_id=None,
                        selected_temporal_target_ids=['KF3'], reason='Opening desk premise is already established; subsequent movement continues.')])
    clip, anchors = project(data, 2, inherited())
    assert clip['capability'] == 'TEMPORAL_EXTEND'
    assert clip['selected_temporal_target_ids'] == ['KF3'] and clip['early_composition_state_id'] is None
    assert [a['source']['id'] for a in anchors] == ['KF3']
    shot, plan = image_plan(tmp_path, data, clip, anchors)
    requirements = project_required_execution_images(shot, plan)
    assert [(r['state_id'], r['kind']) for r in requirements] == [('KF3', 'SELECTED_TEMPORAL_TARGET')]
    anchors[0]['image_url'] = shot.image_url
    previous = dict(clip_index=1, clip_plan_revision=1, generated_by_task_id='approved-c1', result_url='previous.mp4')
    compiled = compile_temporal_extend_clip(shot, plan, clip, 1, previous, anchors)
    assert [a['source']['id'] for a in compiled['execution_contract']['temporal_anchor_manifest']['anchors']] == ['KF3']


def test_carry_in_alone_does_not_supply_coverage():
    with pytest.raises(ValueError, match='EARLY_COMPOSITION_COVERAGE_INVALID'):
        project(round2(), 2)


@pytest.mark.parametrize('conclusion', [
    inherited('KF999'), inherited('KF1'), inherited('KF3'), inherited(target='KF4'),
    inherited(preserved=False), {}, 'KF2',
])
def test_invalid_scope_or_negative_semantic_conclusion_rejected(conclusion):
    with pytest.raises(ValueError, match='INHERITED_COMPOSITION_INVALID'):
        project(round2(), 2, conclusion)


@pytest.mark.parametrize('change', ['missing', 'wrong_time', 'intervening', 'no_reason', 'in_clip'])
def test_inherited_requires_exact_adjacent_evidence_and_exclusive_selection(change):
    data = round2()
    if change == 'missing': data['transition_context'] = []
    if change == 'wrong_time': data['transition_context'][1]['start_time'] = 7.7
    if change == 'intervening':
        data['visual_state_candidates'].append(dict(visual_state_id='KF10', keyframe_index=10,
            time_seconds=8, description='A new blocking premise.', timed_visual_target=False))
    if change == 'no_reason': data['raw_clips'][1]['reason'] = ''
    if change == 'in_clip': data['raw_clips'][1]['early_composition_state_id'] = 'KF2'
    with pytest.raises(ValueError, match='INHERITED_COMPOSITION_INVALID'):
        project(data, 2, inherited())


def test_transition_break_is_a_director_decision_not_keyword_detection():
    data = round2()
    data['transition_context'][1]['transition_description'] = 'Camera resets; a new subject enters a different arrangement.'
    data['raw_clips'][1]['reason'] = 'Canonical transition breaks opening premise; inherited coverage cannot be established.'
    # Mock director withholds inheritance. Code must not upgrade null from carry-in.
    with pytest.raises(ValueError, match='EARLY_COMPOSITION_COVERAGE_INVALID'):
        project(data, 2)
    with pytest.raises(ValueError, match='INHERITED_COMPOSITION_INVALID'):
        project(data, 2, inherited(preserved=False))


def test_round2_c3_requires_its_own_semantic_assessment():
    data = round2()
    data['raw_clips'][2]['reason'] = 'Late transition phase changes pose/framing; KF2 does not establish the required opening with sufficient evidence.'
    with pytest.raises(ValueError, match='EARLY_COMPOSITION_COVERAGE_INVALID'):
        project(data, 3)
    with pytest.raises(ValueError, match='INHERITED_COMPOSITION_INVALID'):
        project(data, 3, inherited(preserved=False))


def test_round2_c6_ongoing_departure_can_inherit_independently(tmp_path):
    data = round2()
    data['raw_clips'][5]['reason'] = 'Audited semantic fixture: KF8 establishes inward-facing guard and two stationary subjects outside with boxes; departure and continuous camera adjustment need no new opening arrangement.'
    clip, anchors = project(data, 6, inherited('KF8', 'KF9'))
    assert clip['capability'] == 'EXTEND' and anchors == []
    assert clip['visual_state_indexes'] == [9] and clip['carry_in_state_index'] == 8
    shot, plan = image_plan(tmp_path, data, clip, anchors)
    assert project_required_execution_images(shot, plan) == []


@pytest.mark.parametrize('continuity', ['NONE', 'CUT'])
def test_noncontinuous_has_no_inherited_coverage(continuity):
    data = round2()
    data['raw_clips'][1]['continuity_to_previous'] = continuity
    clip, anchors = project(data, 2)
    assert clip['capability'] == 'GENERATE' and anchors == []
    with pytest.raises(ValueError, match='INHERITED_COMPOSITION_INVALID'):
        project(data, 2, inherited())


def test_active_speech_still_rejects_in_clip_composition():
    data = round2()
    data['raw_clips'][1]['end_time'] = 24
    data['raw_clips'][1]['early_composition_state_id'] = 'KF3'
    with pytest.raises(ValueError, match='COMPOSITION_SELECTION_INVALID'):
        project(data, 2)


def test_already_active_speech_accepts_only_explicit_prior_inheritance():
    data = round2()
    data['speech_timing_intervals'] = [dict(start_time=8, end_time=10)]
    data['raw_clips'][1]['reason'] = 'Prior canonical composition remains established across this opening despite active speech.'
    clip, anchors = project(data, 2, inherited())
    assert clip['capability'] == 'EXTEND' and anchors == []
    with pytest.raises(ValueError, match='EARLY_COMPOSITION_COVERAGE_INVALID'):
        project(data, 2)


def test_round2_c4_exact_tolerance_is_carry_in_and_cannot_be_inherited_from_future():
    data = round2()
    clips = deepcopy(data['raw_clips'])
    cp._project_clip_visual_states(clips, data['visual_state_candidates'])
    assert 5 in clips[2]['visual_state_indexes']
    assert clips[3]['carry_in_state_index'] == 5 and 5 not in clips[3]['visual_state_indexes']
    with pytest.raises(ValueError, match='COMPOSITION_SELECTION_INVALID'):
        project(data, 4)
    data['raw_clips'][3]['early_composition_state_id'] = None
    with pytest.raises(ValueError, match='INHERITED_COMPOSITION_INVALID'):
        project(data, 4, inherited('KF5', 'KF6'))


@pytest.mark.parametrize('time,owned', [(35.099999, False), (35.10, False), (35.100001, True)])
@pytest.mark.parametrize('timed', [False, True])
def test_precision_ownership_carry_composition_and_timed_selection_agree(time, owned, timed):
    candidates = _candidates([dict(index=1, time_seconds=0, role='START', timed_visual_target=False),
                              dict(index=2, time_seconds=time, timed_visual_target=timed)])
    clip = dict(clip_index=2, start_time=35.05, end_time=39.05, continuity_to_previous='CONTINUOUS',
                previous_clip_index=1, selected_temporal_target_ids=['KF2'] if timed else [],
                early_composition_state_id=None if timed else 'KF2')
    cp._project_clip_visual_states([clip], candidates)
    assert (2 in clip['visual_state_indexes']) is owned
    assert (clip['carry_in_state_index'] == 2) is (not owned)
    if owned:
        cp._project_temporal_targets([clip], candidates, 39.05)
        cp._project_early_composition_states([clip], candidates, [])
        assert clip['capability'] == 'TEMPORAL_EXTEND'
    else:
        with pytest.raises(ValueError, match='TEMPORAL_SELECTION_INVALID' if timed else 'COMPOSITION_SELECTION_INVALID'):
            cp._project_temporal_targets([clip], candidates, 39.05)
            cp._project_early_composition_states([clip], candidates, [])
    # Independently validate the same boundary rule, including a forged owned index.
    check = dict(clip, capability='GENERATE', visual_state_indexes=[2], planned_duration=4)
    result = validate_clip_plan(39.05, [check], [], visual_state_candidates=candidates)
    assert ('VISUAL_STATE_OWNERSHIP_INVALID' in [f['code'] for f in result['blocking']]) is (not owned)
    check.update(visual_state_indexes=[], carry_in_state_index=2)
    result = validate_clip_plan(39.05, [check], [], visual_state_candidates=candidates)
    assert ('CARRY_IN_INVALID' in [f['code'] for f in result['blocking']]) is owned


@pytest.mark.asyncio
@pytest.mark.parametrize('valid,boundary', [(True, 5), (False, 5), (True, 5.001)])
async def test_mocked_planning_persists_only_valid_inherited_candidate(db_session, tmp_path, monkeypatch, valid, boundary):
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    from app.api import shots as api
    from app.repositories import NovelRepository, ShotRepository
    from app.models.task import Task
    from test_two_stage_temporal_decision import _db_fixture
    novel, chapter, shot, _, artifact = _db_fixture(db_session, tmp_path)
    states = [dict(index=1, role='START', time_seconds=0, description=None, timed_visual_target=False),
              dict(index=2, time_seconds=4.8, description='Two subjects across a desk, folder stationary.', timed_visual_target=False),
              dict(index=3, time_seconds=8, description='Continuous later movement toward window.', timed_visual_target=False)]
    plan = json.loads(shot.video_director_plan)
    plan.update(keyframes=states, transitions=[dict(from_keyframe_index=2, to_keyframe_index=3,
        start_time=4.8, end_time=8, transition_description='Opening desk/axis/props preserved; later continuous movement toward window.')])
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    before = shot.video_director_plan
    count = db_session.query(Task).count()
    raw = [dict(clip_index=1, start_time=0, end_time=boundary, continuity_to_previous='NONE',
                early_composition_state_id=None, selected_temporal_target_ids=[]),
           dict(clip_index=2, start_time=boundary, end_time=12, continuity_to_previous='CONTINUOUS',
                previous_clip_index=1, early_composition_state_id=None, selected_temporal_target_ids=[],
                inherited_start_composition=inherited('KF2' if valid else 'KF999'),
                reason='Established two-subject desk composition and folder remain at the opening; continuous motion needs no reset.')]
    template = (Path(__file__).parents[1] / 'prompt_templates/10A_NovelFlow_ClipExecutionPlanner_V1.txt').read_text()
    monkeypatch.setattr(cp.PromptTemplateService, 'get_default_system_template', lambda *_: SimpleNamespace(template=template, name='planner'))
    fixed = deepcopy(raw)
    fixed[0]['end_time'] = fixed[1]['start_time'] = 5
    llm = AsyncMock(side_effect=[{'success':True, 'content':json.dumps({'clips':candidate})}
                                for candidate in (raw, fixed)])
    monkeypatch.setattr(cp.LLMService, 'chat_completion', llm)
    args = (novel.id, chapter.id, shot.id, api.PlanClipsRequest(force=True), db_session,
            NovelRepository(db_session), ShotRepository(db_session))
    if valid:
        result = await api.plan_shot_clips(*args)
        assert result['data']['validation']['passed']
        db_session.refresh(shot)
        saved = json.loads(shot.video_director_plan)
        assert saved['clip_plan_validation']['composition_contract'] == 'EARLY_COMPOSITION_V2'
        assert saved['clip_plan'][1]['capability'] == 'EXTEND' and saved['temporal_anchors'] == []
    else:
        with pytest.raises(HTTPException) as error:
            await api.plan_shot_clips(*args)
        assert error.value.status_code == 400 and 'INHERITED_COMPOSITION_INVALID' in str(error.value.detail)
        db_session.refresh(shot)
        assert shot.video_director_plan == before
    assert llm.await_count == (2 if boundary != 5 else 1)
    if boundary != 5:
        retry = json.loads(llm.await_args.kwargs['user_content'])['continuity_revalidation']
        assert retry['normalized_clips'][1]['start_time'] == 5
        assert 'Re-evaluate inherited_start_composition' in retry['instruction']
    assert db_session.query(Task).count() == count and artifact.read_bytes() == b'historical'


def test_normalization_must_revalidate_inherited_boundary_phase_even_without_identity_drift():
    data = round2()
    clips = deepcopy(data['raw_clips'])
    clips[1]['inherited_start_composition'] = inherited()
    before = cp._canonical_continuity_structure(clips, data['visual_state_candidates'])
    clips[0]['end_time'] = clips[1]['start_time'] = 8.16
    after = cp._canonical_continuity_structure(clips, data['visual_state_candidates'])
    assert before[1]['carry_in_state_index'] == after[1]['carry_in_state_index']
    assert cp._continuity_premise_changed(before, after, data['visual_state_candidates'])


def test_prompt_owns_preservation_and_no_speech_action_quality():
    prompt = (Path(__file__).parents[1] / 'prompt_templates/10A_NovelFlow_ClipExecutionPlanner_V1.txt').read_text()
    for rule in ['Neither\n   CONTINUOUS nor the existence of a carry-in proves inherited coverage',
                 'major blocking relocation', 'relevant subject\n   entrance/exit',
                 'old pose/framing no longer grounds', 'Use no fixed age threshold',
                 'Merely being before Clip end is insufficient', 'EARLY_COMPOSITION_V2']:
        assert rule in prompt
