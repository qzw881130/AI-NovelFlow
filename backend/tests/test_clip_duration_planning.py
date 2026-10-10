import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app.services import clip_planner as planner
from app.services.clip_duration_planning import workflow_planning_budget, observe_duration_plan, load_planning_budgets
from app.services import h3_execution_optimizer as opt


def workflow():
    values = json.loads((Path(__file__).parent / 'fixtures/h3_continuation_workflow.json').read_text())
    return NS(**{**values, 'extension': '{}', 'is_active': True})


def shot(duration, events=()):
    return NS(id='shot', chapter_id='chapter', duration=duration, continuity_mode='NORMAL',
              description='', video_description='', dialogues=json.dumps(list(events), ensure_ascii=False),
              keyframes='[]', video_director_plan='{}', characters='[]', props='[]')


def response_clips(*ends):
    starts = (0, *ends[:-1])
    return [{'clip_index': i, 'start_time': start, 'end_time': end,
             'continuity_to_previous': 'NONE' if i == 1 else 'CUT',
             'selected_temporal_target_ids': [], 'reason': 'Complete natural beat; preserve the whole utterance.'}
            for i, (start, end) in enumerate(zip(starts, ends), 1)]


def setup_planner(monkeypatch, clips, budgets=None):
    prompt = (Path(__file__).parents[1] / 'prompt_templates/10A_NovelFlow_ClipExecutionPlanner_V1.txt').read_text()
    monkeypatch.setattr(planner, 'PromptTemplateService', lambda db: NS(
        get_default_system_template=lambda name: NS(name='planner', template=prompt)))
    chat = AsyncMock(return_value={'success': True, 'content': json.dumps({'clips': clips})})
    monkeypatch.setattr(planner, 'LLMService', lambda: NS(chat_completion=chat))
    monkeypatch.setattr(planner, 'load_planning_budgets', lambda db: budgets or {})
    return chat


@pytest.mark.asyncio
async def test_soft_target_is_in_request_and_natural_short_clips_stay_short(monkeypatch):
    chat = setup_planner(monkeypatch, response_clips(12, 24))
    subject = shot(24)
    original = vars(subject).copy()
    clips, validation = await planner.plan_clips(None, NS(id='novel'), subject, [])
    sent = json.loads(chat.call_args.kwargs['user_content'])
    assert sent['planning_policy']['preferred_max_duration'] == 15
    assert sent['planning_policy']['max_story_clip_duration'] == 20
    assert 'SOFT target' in chat.call_args.kwargs['system_prompt']
    assert validation['passed'] and [c['planned_duration'] for c in clips] == [12, 12]
    assert all(c['duration_planning']['overlap_duration'] == 0 for c in clips)
    assert all(c['duration_planning']['status'] == 'WITHIN_PREFERRED' for c in clips)
    assert vars(subject) == original and chat.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('duration', [15.5, 18, 20])
async def test_long_complete_utterance_is_not_split_to_hit_preference(monkeypatch, duration):
    event = {'id': 'D1', 'speaker': 'speaker', 'text': '完整对白不能被拆断。',
             'start_time': 0, 'end_time': duration}
    subject = shot(duration, [event])
    canonical = copy.deepcopy(event)
    chat = setup_planner(monkeypatch, response_clips(duration))
    clips, validation = await planner.plan_clips(None, NS(id='novel'), subject, [],
                                               resolved_dialogue_timeline=[event])
    assert validation['passed'] and len(clips) == 1 and chat.await_count == 1
    assigned, = clips[0]['dialogue_assignment']
    assert assigned['text'] == event['text'] and assigned['speaker'] == 'speaker'
    assert assigned['end_time'] - assigned['start_time'] == duration
    assert not assigned['continues_in_next_clip']
    observation = clips[0]['duration_planning']
    assert observation['status'] == 'ABOVE_PREFERRED' and observation['reason']
    assert not observation['reason_missing'] and event == canonical


@pytest.mark.asyncio
async def test_boundary_in_speech_moves_to_end_even_when_clip_exceeds_fifteen(monkeypatch):
    event = {'id': 'D1', 'speaker': 'speaker', 'text': '完整长句。', 'start_time': 0, 'end_time': 17}
    setup_planner(monkeypatch, response_clips(15, 24))
    clips, validation = await planner.plan_clips(None, NS(id='novel'), shot(24, [event]), [],
                                               resolved_dialogue_timeline=[event])
    assert validation['passed']
    assert [(c['start_time'], c['end_time']) for c in clips] == [(0, 17), (17, 24)]
    assert len(clips[0]['dialogue_assignment']) == 1 and clips[1]['dialogue_assignment'] == []


@pytest.mark.asyncio
async def test_unsplittable_utterance_over_hard_ceiling_reports_infeasible(monkeypatch):
    event = {'id': 'D1', 'speaker': 'speaker', 'text': '不可拆分。', 'start_time': 0, 'end_time': 21}
    chat = setup_planner(monkeypatch, response_clips(21))
    with pytest.raises(ValueError, match='DURATION_INFEASIBLE'):
        await planner.plan_clips(None, NS(id='novel'), shot(21, [event]), [], resolved_dialogue_timeline=[event])
    chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrepairable_boundary_does_not_silently_segment_a_sentence(monkeypatch):
    # Neither endpoint can repair this two-Clip proposal within 4..20. Replan it.
    event = {'id': 'D1', 'speaker': 'speaker', 'text': '不可截断。', 'start_time': 10, 'end_time': 25}
    setup_planner(monkeypatch, response_clips(20, 40))
    with pytest.raises(ValueError, match='CLIP_BOUNDARY_INSIDE_DIALOGUE'):
        await planner.plan_clips(None, NS(id='novel'), shot(40, [event]), [], resolved_dialogue_timeline=[event])


def test_actual_continuation_configuration_and_standard_are_separate():
    w = workflow()
    before = copy.deepcopy(vars(w))
    budget = workflow_planning_budget(w)
    assert (budget['overlap_frames'], budget['fps'], budget['overlap_duration']) == (39, 24, 1.625)
    assert vars(w) == before
    clip = {'capability': 'EXTEND', 'start_time': 0, 'end_time': 14}
    speech = [{'start_time': 0, 'end_time': 12}]
    observed = observe_duration_plan(clip, speech, {'EXTEND': budget})
    assert observed['minimum_execution_duration'] == 13.625
    assert observed['planned_story_duration'] == 14 and clip['start_time'] == 0
    w.type = 'multi_reference_video'
    standard = workflow_planning_budget(w)
    assert standard['overlap_duration'] == 0 and 'overlap_frames' not in standard
    # Identical graph/KFs cannot turn ordinary generation into continuation.
    ordinary = observe_duration_plan({**clip, 'capability': 'GENERATE'}, speech, {'GENERATE': standard})
    assert ordinary['minimum_execution_duration'] == 12


def test_unrecognized_or_mismatched_continuation_never_assumes_39(monkeypatch):
    w = workflow()
    graph = json.loads(w.workflow_json)
    masked = next(n['inputs'] for n in graph.values() if n['class_type'] == 'MiniMaxH3StartMaskedContext')
    masked['source_fps'] = 30
    w.workflow_json = json.dumps(graph)
    assert workflow_planning_budget(w)['overlap_duration'] is None
    unknown = observe_duration_plan({'capability': 'EXTEND', 'start_time': 0, 'end_time': 12}, [], {})
    assert unknown['minimum_execution_duration'] is None
    w.type = 'multi_reference_video'
    from app.services import clip_duration_planning as budgets
    monkeypatch.setattr(budgets, 'WorkflowRepository', lambda db: NS(
        get_by_id=lambda id: w, get_active_by_type=lambda family: None))
    assert load_planning_budgets(object()) == {}


def test_real_lower_limit_and_missing_reason_are_observable_without_soft_gate():
    budget = workflow_planning_budget(workflow())
    clip = {'capability': 'EXTEND', 'start_time': 0, 'end_time': 19}
    speech = [{'start_time': 0, 'end_time': 19}]
    assert observe_duration_plan(clip, speech, {'EXTEND': budget})['status'] == 'DURATION_INFEASIBLE'
    shorter = {'start_time': 0, 'end_time': 16, 'capability': 'GENERATE'}
    legal = observe_duration_plan(shorter, [], {})
    assert legal['status'] == 'ABOVE_PREFERRED' and legal['reason_missing']
    assert observe_duration_plan(shorter, [], {'GENERATE': {'max_duration': 14}})['status'] == 'DURATION_INFEASIBLE'


@pytest.mark.parametrize('overlap,maximum,expected', [(0, 20, False), (1.625, 20, True), (0, 18, True)])
def test_optimizer_returns_replan_only_for_proven_hard_budget(overlap, maximum, expected):
    authority = {'dialogue_events': [{'duration': 10}, {'duration': 9}],
                 'continuation': {'overlap_seconds': overlap}}
    result = opt.duration_infeasibility(authority, {'maximum': maximum})
    assert bool(result) is expected
    if expected:
        assert result['code'] == 'DURATION_INFEASIBLE' and result['requires_clip_replan']
    authority['allowed_dialogue_overlaps'] = [['D1', 'D2']]
    assert opt.duration_infeasibility(authority, {'maximum': maximum}) is None
