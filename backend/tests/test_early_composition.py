"""Clip-local composition semantics, merged conditioning and clean-cut legacy gates."""
import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

from app.services import clip_planner
from app.services.clip_execution_compiler import (
    EARLY_COMPOSITION_CONTRACT, TEMPORAL_DECISION_CONTRACT,
    ClipExecutionCompileError, compile_temporal_extend_clip,
    get_canonical_execution_readiness, project_temporal_anchor_positions,
)
from app.services.required_visual_state_images import (
    prepare_required_images, project_required_execution_images,
)
from test_two_stage_temporal_decision import _candidates, _clips, _states, _db_fixture


def project(composition='KF4', timed=None, continuity='CONTINUOUS', speech=(), states=None):
    candidates = _candidates(states)
    clips = _clips(timed, continuity)
    clips[1]['early_composition_state_id'] = composition
    clip_planner._project_clip_visual_states(clips, candidates)
    clip_planner._project_temporal_targets(clips, candidates, 12)
    clip_planner._project_early_composition_states(clips, candidates, list(speech))
    anchors = clip_planner._build_temporal_anchors(clips, candidates)
    return clips, anchors


def current_plan(tmp_path, composition='KF4', timed=None):
    image = tmp_path / 'main.png'
    image.write_bytes(b'image')
    clips, anchors = project(composition, timed)
    plan = dict(canonical_visual_plan=True, keyframes=_states(), clip_plan=clips,
                clip_plan_revision=1, temporal_anchors=anchors,
                clip_plan_validation=dict(passed=True, temporal_contract=TEMPORAL_DECISION_CONTRACT,
                                          composition_contract=EARLY_COMPOSITION_CONTRACT))
    plan['keyframes'][-1]['timed_visual_target'] = False  # unselected owned ordinary state stays optional
    shot = SimpleNamespace(id='shot', description='scene', image_url=str(image), image_path=str(image),
                           image_task_id=None, keyframes='[]', video_director_plan=json.dumps(plan))
    return shot, plan


@pytest.mark.parametrize('composition,timed,expected', [
    ('KF4', [], ['KF4']), (None, ['KF3'], ['KF3']),
    ('KF4', ['KF3'], ['KF3', 'KF4']), ('KF3', ['KF3'], ['KF3']),
])
def test_semantic_split_physical_merge(composition, timed, expected):
    clips, anchors = project(composition, timed)
    assert clips[1]['capability'] == 'TEMPORAL_EXTEND'
    assert clips[1]['requires_temporal_control'] is True
    assert clips[1]['selected_temporal_target_ids'] == timed
    assert [a['source']['id'] for a in anchors] == expected
    assert len(clips[1]['temporal_anchor_ids']) == len(expected)


def test_false_still_cannot_be_selected_as_timed():
    with pytest.raises(ValueError, match='TEMPORAL_SELECTION_INVALID'):
        project('KF4', ['KF4'])


@pytest.mark.parametrize('composition', ['KF2', 'KF1', 'KF999', 'KF5', '', ['KF4']])
def test_carry_nonowned_endpoint_or_invalid_identity_rejected(composition):
    with pytest.raises(ValueError, match='COMPOSITION_SELECTION_INVALID'):
        project(composition)


@pytest.mark.parametrize('start,end', [(9, 11), (6, 9), (4, 7), (10, 11)])
def test_state_must_precede_first_overlapping_speech(start, end):
    with pytest.raises(ValueError, match='COMPOSITION_SELECTION_INVALID'):
        project(speech=[dict(start_time=start, end_time=end)])


def test_pre_speech_state_and_unrelated_intervals_allowed():
    project(speech=[dict(start_time=2, end_time=6), dict(start_time=10.1, end_time=11)])


def test_continuous_neither_and_late_timed_only_fail_coverage():
    for timed in ([], ['KF5']):
        with pytest.raises(ValueError, match='EARLY_COMPOSITION_COVERAGE_INVALID'):
            project(None, timed)


@pytest.mark.parametrize('available', [True, False])
def test_early_candidate_availability_cannot_reclassify_continuity(available):
    candidates = _candidates()
    if not available:
        candidates = [state for state in candidates if state['time_seconds'] in (0, 6, 12)]
    clips = _clips([])
    clips[1]['early_composition_state_id'] = 'KF4' if available else None
    clip_planner._project_clip_visual_states(clips, candidates)
    clip_planner._project_temporal_targets(clips, candidates, 12)
    before = deepcopy(clips)
    if available:
        clip_planner._project_early_composition_states(clips, candidates, [])
        assert clips[1]['capability'] == 'TEMPORAL_EXTEND'
    else:
        with pytest.raises(ValueError, match='EARLY_COMPOSITION_COVERAGE_INVALID'):
            clip_planner._project_early_composition_states(clips, candidates, [])
        assert clips == before
        assert clips[1]['carry_in_state_index'] == 2
        assert clips[1]['visual_state_indexes'] == [5]
    assert clips[1]['continuity_to_previous'] == 'CONTINUOUS'


def test_cut_and_first_generate_need_no_composition():
    clips, anchors = project(None, [], 'CUT')
    assert all(c['capability'] == 'GENERATE' for c in clips)
    assert anchors == []
    with pytest.raises(ValueError, match='NONE/CUT'):
        project('KF4', [], 'CUT')


def test_missing_field_is_not_auto_upgraded():
    clips = _clips(['KF3'])
    del clips[1]['early_composition_state_id']
    clip_planner._project_clip_visual_states(clips, _candidates())
    with pytest.raises(ValueError, match='is required'):
        clip_planner._project_early_composition_states(clips, _candidates(), [])


def test_composition_missing_image_blocks_without_downgrade_then_ready(tmp_path):
    shot, plan = current_plan(tmp_path)
    before = deepcopy(plan)
    result = get_canonical_execution_readiness(shot, plan)
    assert result['code'] == 'TEMPORAL_ANCHOR_UNAVAILABLE'
    assert result['blocking_clips'][0]['visual_state_index'] == 4
    items = project_required_execution_images(shot, plan)
    assert [(i['state_id'], i['kind']) for i in items] == [('KF1', 'GENERATE_VISUAL_START'), ('KF4', 'EARLY_COMPOSITION')]
    assert items[1]['consumers'][0]['clip_local_time'] == 4
    assert not items[1]['ready'] and plan == before
    assert plan['clip_plan'][1]['capability'] == 'TEMPORAL_EXTEND'
    from app.services.canonical_execution_invalidation import sync_temporal_anchor_state_image
    plan['keyframes'][3]['image_url'] = shot.image_url
    sync_temporal_anchor_state_image(plan, 4, shot.image_url, 'image-task')
    shot.video_director_plan = json.dumps(plan)
    assert get_canonical_execution_readiness(shot, plan)['ready'] is True
    assert all(i['ready'] for i in project_required_execution_images(shot, plan))
    assert not {2, 3, 5}.intersection(i['state_index'] for i in items)


def test_shared_timed_composition_image_one_requirement_two_reasons(tmp_path):
    shot, plan = current_plan(tmp_path, 'KF3', ['KF3'])
    items = project_required_execution_images(shot, plan)
    assert [i['state_index'] for i in items] == [1, 3]
    assert {c['kind'] for c in items[1]['consumers']} == {'SELECTED_TEMPORAL_TARGET', 'EARLY_COMPOSITION'}


def test_export_reports_ordinary_composition_required_without_timed_promotion(tmp_path):
    from app.services.canonical_export import _state_records, _clip_summary
    shot, plan = current_plan(tmp_path)
    with ZipFile(BytesIO(), 'w') as archive:
        records = _state_records(archive, set(), 'novel', shot, plan, 'states', [])
    state = next(r for r in records if r['index'] == 4)
    assert state['required'] and state['early_composition_selected']
    assert not state['timed_visual_target'] and not state['selected_temporal_target']
    assert _clip_summary(plan['clip_plan'][1])['early_composition_state_id'] == 'KF4'


def test_false_composition_compiles_with_unchanged_previous_av_provenance(tmp_path):
    shot, plan = current_plan(tmp_path)
    anchors = plan['temporal_anchors']
    anchors[0]['image_url'] = shot.image_url
    previous = dict(clip_index=1, clip_plan_revision=1, generated_by_task_id='previous', result_url='previous.mp4')
    result = compile_temporal_extend_clip(shot, plan, plan['clip_plan'][1], 1, previous, anchors)
    contract = result['execution_contract']
    assert contract['previous_clip']['generated_by_task_id'] == 'previous'
    physical = contract['temporal_anchor_manifest']['anchors']
    assert len(physical) == 1 and physical[0]['source']['id'] == 'KF4'
    assert 1 < physical[0]['frame_position']


def test_merged_anchor_limit_includes_composition():
    states = [dict(index=1, time_seconds=0, timed_visual_target=False)]
    states += [dict(index=i, time_seconds=6.1 + (i-2)*.5, timed_visual_target=i != 10) for i in range(2,11)]
    with pytest.raises(ValueError, match='TEMPORAL_ANCHOR_LIMIT'):
        project('KF10', [f'KF{i}' for i in range(2,10)], states=states)


def test_merged_duplicate_time_and_physical_position_still_fail():
    states = _states()
    states[3]['time_seconds'] = 8
    with pytest.raises(ValueError, match='duplicate temporal target time'):
        project('KF4', ['KF3'], states=states)
    _, anchors = project('KF4', ['KF3'])
    for a in anchors: a['image_url'] = 'image.png'
    anchors[1]['time_seconds'] = anchors[0]['time_seconds'] + .001
    with pytest.raises(ClipExecutionCompileError, match='duplicate projected frame'):
        project_temporal_anchor_positions(anchors, 6)


def test_old_marker_cannot_claim_composition_without_replan(tmp_path):
    shot, plan = current_plan(tmp_path)
    del plan['clip_plan_validation']['composition_contract']
    before = deepcopy(plan)
    assert get_canonical_execution_readiness(shot, plan)['code'] == 'COMPOSITION_CONTRACT_REPLAN_REQUIRED'
    assert project_required_execution_images(shot, plan) == []
    assert plan == before


@pytest.mark.parametrize('endpoint', ['single', 'batch', 'retry', 'prepare'])
def test_legacy_temporal_marker_rejects_all_mutating_execution_entrypoints(client, db_session, tmp_path, endpoint):
    novel, chapter, shot, task, artifact = _db_fixture(db_session, tmp_path)
    plan = json.loads(shot.video_director_plan)
    del plan['clip_plan_validation']['composition_contract']
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    before = shot.video_director_plan
    if endpoint == 'retry':
        from app.services.task_service import TaskService
        response = TaskService(db_session).retry_task(task.id)
        assert response['status_code'] == 409
        assert response['success'] is False and '早期构图覆盖' in response['message']
    elif endpoint == 'prepare':
        # Exercise the same shared preparation gate without starting tasks.
        import asyncio
        from app.services.canonical_execution_invalidation import CanonicalExecutionConflict
        with pytest.raises(CanonicalExecutionConflict, match='COMPOSITION_CONTRACT_REPLAN_REQUIRED'):
            asyncio.run(prepare_required_images(db_session, shot, 7, AsyncMock(), AsyncMock()))
    else:
        root = f'/api/novels/{novel.id}/chapters/{chapter.id}'
        response = client.post(f'{root}/shots/{shot.id}/video-director/clips/2/generate', json={'clip_plan_revision':7}) if endpoint == 'single' else client.post(f'{root}/shot-videos/batch', json={'shot_ids':[shot.id]})
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'COMPOSITION_CONTRACT_REPLAN_REQUIRED'
    db_session.refresh(shot)
    assert shot.video_director_plan == before and artifact.read_bytes() == b'historical'


@pytest.mark.asyncio
async def test_composition_uses_existing_image_preparation_route(db_session, tmp_path):
    _, _, shot, _, _ = _db_fixture(db_session, tmp_path)
    plan = json.loads(shot.video_director_plan)
    clips, anchors = project()
    plan.update(clip_plan=clips, temporal_anchors=anchors)
    shot.video_director_plan = json.dumps(plan)
    shot.keyframes = json.dumps([dict(frame_index=2, plan_keyframe_index=4, description='composition')])
    db_session.commit()
    submit, start = AsyncMock(return_value='composition-image'), AsyncMock()
    result = await prepare_required_images(db_session, shot, 7, submit, start, clip_indexes=[2])
    assert len(result) == 1 and result[0]['state_id'] == 'KF4' and result[0]['status'] == 'QUEUED'
    assert submit.await_args.args[0] == 0  # existing frame mapping, no new Task type
    assert submit.await_args.args[1]['state_index'] == 4
    start.assert_not_awaited()


def test_prompts_preserve_split_authority_and_state_time_visible_cast():
    root = Path(__file__).parents[1] / 'prompt_templates'
    p8 = (root/'08_NovelFlow_VideoDirector_KeyframePlanner_V2_3Frame4Frame.txt').read_text()
    p9 = (root/'09_NovelFlow_QwenEdit2511_KeyframeImagePrompt_V1.txt').read_text()
    p10 = (root/'10A_NovelFlow_ClipExecutionPlanner_V1.txt').read_text()
    assert 'pre-event' in p8 and '最终 Clip topology' in p8
    assert '机械补状态' in p8 and 'dialogue_timeline_source' in p8
    assert '当前 Visual State' in p9 and '尚未入场' in p9
    assert '不得删除' in p9 and '当前状态' in p9
    assert 'early_composition_state_id' in p10 and 'selected_temporal_target_ids' in p10
    assert 'ELIGIBLE_THEN_SELECTED_V1' in p10
