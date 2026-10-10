"""Camera choice is model planning freedom; source facts and timing stay strict."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from app.models.prompt_template import PromptTemplate
from app.services import h3_execution_optimizer as opt
from app.services.prompt_template_service import PromptTemplateService, SYSTEM_H3_VIDEO_PROMPT_TEMPLATES

FIXTURES = Path(__file__).parent / 'fixtures'


def saved(name):
    return json.loads((FIXTURES / f'h3_v5_{name}.json').read_text())


@pytest.mark.parametrize('mode', ['SINGLE_FRAME', 'FIRST_LAST_FRAME', 'MULTI_KEYFRAME', 'EXTEND'])
def test_camera_choice_does_not_change_authority_or_invent_context(monkeypatch, mode):
    raw = '''duration: 4s
<Subject 1> is A, stable face.
CONTINUOUS_TAKE: initial ensemble view.
D1:
  speaker: <Subject 1>
  start_time: 2s
  end_time: 3s
  exact_dialogue: 问？
'''
    clip = {'planned_duration': 4, 'clip_index': 1}
    context = {'continuity_mode': 'CONTINUOUS_TAKE'}
    path = None
    if mode == 'EXTEND':
        context.update(capability=mode, continuation=saved('c3_fragment_provenance')['authority']['continuation'])
        path = '/read-only-previous.mp4'
    before = copy.deepcopy((clip, context))
    previews = [{'logical_id': 'PreviousFrame1', 'context_frames': 39, 'source_frame_index': 646}]
    monkeypatch.setattr(opt, 'previous_video_frames', lambda *args: copy.deepcopy(previews))
    runtime, images = opt.build_runtime_input(raw, mode, clip, previous_video_path=path, execution_context=context)
    assert (clip, context) == before and runtime['raw_h3_prompt'] == raw
    assert runtime['clip']['continuity_mode'] == 'CONTINUOUS_TAKE'  # retained input, not rewritten
    assert 'VISIBILITY_ADAPTIVE_CAMERA' in runtime['execution_flexibility']['inter_anchor_camera_path']
    policy = runtime['execution_flexibility']['speaker_camera_selection']
    assert all(option in policy for option in ['maintain a readable view', 'continuous reframing', 'explicit cut'])
    assert runtime['immutable_authority']['dialogue_events'] == [
        {'id': 'D1', 'speaker': '<Subject 1>', 'exact_dialogue': '问？', 'duration': 1.0, 'order': 1}]
    assert runtime['initial_execution_timing']['dialogue_events'][0]['start_time'] == 2
    assert runtime['native_prompt_contract']['speaker_bindings'] == {'<Subject 1>': 'S1'}
    assert runtime['duration_limits']['maximum'] == 20
    if mode == 'EXTEND':
        assert runtime['execution_mode'] == 'VIDEO_CONTINUATION' and images == previews
        assert runtime['immutable_authority']['continuation'] == context['continuation']
        assert context['continuation']['context_frames'] == 39
        assert context['continuation']['overlap_seconds'] == 1.625
        assert 'after the verified context prefix' in runtime['execution_flexibility']['camera_context_boundary']
    else:
        assert runtime['execution_mode'] == 'STANDARD_GENERATION' and not images
        assert 'continuation' not in runtime['immutable_authority']
        assert runtime['previous_video_context']['present'] is False
        assert 'no previous-video prefix' in runtime['execution_flexibility']['camera_context_boundary']


def test_system_registry_update_preserves_override_and_exposes_policy(db_session):
    item = next(t for t in SYSTEM_H3_VIDEO_PROMPT_TEMPLATES if t['type'] == opt.TEMPLATE_TYPE)
    system = PromptTemplate(name=item['name'], type=opt.TEMPLATE_TYPE, template='stale no-cut rule', is_system=True, is_active=True)
    custom = PromptTemplate(name='private14', type=opt.TEMPLATE_TYPE, template='user-owned', is_system=False, is_active=True)
    db_session.add_all([system, custom]); db_session.commit(); ids = (system.id, custom.id)
    PromptTemplateService(db_session).init_system_templates()
    assert (system.id, custom.id) == ids and custom.template == 'user-owned'
    chosen = opt.resolve_prompt_template(db_session, NS(h3_execution_optimizer_prompt_template_id=None),
                                       'h3_execution_optimizer_prompt_template_id', opt.TEMPLATE_TYPE)
    assert chosen.id == system.id and chosen.template == item['template']
    text = chosen.template
    assert 'Maintain the current view when that speaker is already clearly readable' in text
    assert 'Prefer an explicit cut' in text and 'Do not force every line into a close-up' in text
    assert 'first speaker' in text and 'only after that\nprefix ends' in text
    assert 'Keep the internal\nplan, summary and detailed_description consistent' in text
    assert 'CONTINUOUS_TAKE means no hard cut' not in text
    assert not any(s in text for s in ['D11', 'KF4', 'upper chest to just above his crown', 'orange cloth'])


@pytest.mark.parametrize('name,expected_duration,context_frames', [
    ('approved_c1', 15.0, None), ('c2_repeated_provenance', 15.0, 39), ('c3_fragment_provenance', 18.0, 39),
])
def test_saved_c1_c2_c3_stay_valid_and_are_not_recompiled(name, expected_duration, context_frames):
    s = saved(name); before = copy.deepcopy(s)
    result = opt.check_authority(s['raw_prompt'], s['output'], s['authority'], s['initial'], s['limits'])
    assert result['passed'], result['blocking_findings']
    record = {'status': 'OPTIMIZED', 'authority_check': result, 'output': s['output'], 'optimized_prompt': s['output']['optimized_prompt']}
    assert opt.effective_execution_duration(s['initial']['duration'], record, s['limits'])['effective_duration'] == expected_duration
    assert (s['authority'].get('continuation') or {}).get('context_frames') == context_frames
    assert result['checks']['stable_speaker_ids']
    assert result['checks']['execution_budget_explained']
    assert result['checks']['reference_projection_consistent']
    assert s == before
