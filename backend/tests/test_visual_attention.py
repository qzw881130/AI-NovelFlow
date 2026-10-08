"""Offline attention authority, runtime wiring and reuse correctness."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import visual_attention as va
from app.services import video_director_ai as h3
from app.services import shot_video_service as video
from app.api import shots as api
from app.services.clip_execution_compiler import compile_generate_clip, compile_extend_clip, compile_temporal_extend_clip

A = '00000000-0000-4000-8000-000000000001'
B = '00000000-0000-4000-8000-000000000002'
C = '00000000-0000-4000-8000-000000000003'
CAT = [{'character_id': A, 'character_name': 'Mira'}, {'character_id': B, 'character_name': 'Jun'},
       {'character_id': C, 'character_name': 'Kato'}]


def window(start=10, end=14, primary=None, background=None, **extra):
    return {'start_time_seconds': start, 'end_time_seconds': end,
            'primary_subjects': [A] if primary is None else primary,
            'background_motion_subjects': [B] if background is None else background, **extra}


def authority(windows=None):
    return va.normalize_visual_attention({'windows': windows if windows is not None else [window()]}, CAT, 24)['authority']


def state(index=2, time=12):
    return {'index': index, 'time_seconds': time, 'role': 'INTERMEDIATE', 'timed_visual_target': False,
            'description': 'Scene: room\nCharacters:\n- Jun: near doorway\n- Mira: beside table\nAction: Hands at rest.'}


def plan_clip(windows=None):
    clip = {'clip_index': 2, 'start_time': 10, 'end_time': 18, 'visual_state_indexes': [2],
            'carry_in_state_index': 1, 'capability': 'EXTEND', 'continuity_to_previous': 'CONTINUOUS'}
    plan = {'visual_attention': authority(windows), 'keyframes': [state()], 'clip_plan': [clip],
            'transitions': [{'from_keyframe_index': 1, 'to_keyframe_index': 2, 'start_time': 0,
                             'end_time': 12, 'transition_description': 'Jun approaches the table.'}]}
    return plan, clip


def prepared(plan, clip, manifest=None):
    return h3.prepare_clip_visual_attention(plan, clip, ['Mira', 'Jun', 'Kato'], manifest=manifest, duration=24)


@pytest.mark.parametrize('mutation', [
    lambda w: w.update(start_time_seconds=True),
    lambda w: w.update(end_time_seconds=float('nan')),
    lambda w: w.update(start_time_seconds=-1),
    lambda w: w.update(end_time_seconds=25),
    lambda w: w.update(end_time_seconds=10),
    lambda w: w.update(primary_subjects=['Mira']),
    lambda w: w.update(primary_subjects=['<Subject 1>']),
    lambda w: w.update(primary_subjects=[C], background_motion_subjects=[C]),
    lambda w: w.update(handoff={'from': [A], 'to': [B]}),
])
def test_bad_optional_attention_falls_back_as_whole_without_clamping(mutation):
    w = window(); mutation(w)
    result = va.normalize_visual_attention({'windows': [w]}, CAT, 24)
    assert result['status'] == 'FALLBACK_INVALID' and result['authority'] is None and result['findings']


def test_catalog_requires_exact_unique_formal_uuid():
    catalog, warnings = va.character_catalog(['Mira', 'Jun'], [SimpleNamespace(name='Mira', id=A),
        SimpleNamespace(name='Mira', id=C), SimpleNamespace(name='Juno', id=B)])
    assert catalog == [] and len(warnings) == 2
    assert va.normalize_visual_attention({'windows': [window()]}, catalog, 24)['status'] == 'FALLBACK_INVALID'


@pytest.mark.parametrize('raw,status', [(None, 'ABSENT'), ({'windows': []}, 'EMPTY'),
                                        ({'version': 2, 'windows': []}, 'FALLBACK_INVALID')])
def test_absent_empty_bad_version(raw, status):
    assert va.normalize_visual_attention(raw, CAT, 24)['status'] == status


def test_overlaps_rejected_adjacent_and_duplicate_subject_ids_normalize():
    assert va.normalize_visual_attention({'windows': [window(1, 3), window(2, 4)]}, CAT, 24)['status'] == 'FALLBACK_INVALID'
    value = va.normalize_visual_attention({'windows': [window(3, 4), window(1, 3, [A, A])]}, CAT, 24)
    assert [w['start_time_seconds'] for w in value['authority']['windows']] == [1, 3]
    assert value['authority']['windows'][0]['primary_subjects'] == [A]


def test_projection_intersection_handoff_progress_and_no_boundary_restart():
    source = authority([window(10, 14, [A, B], [], handoff={'from': [A], 'to': [B]})])
    before = copy.deepcopy(source)
    left = va.project_visual_attention(source, 11, 12)
    assert left['windows'][0]['start_time_seconds'] == 0
    assert left['windows'][0]['end_time_seconds'] == 1
    assert left['windows'][0]['handoff_progress'] == {'start': .25, 'end': .5}
    shot = va.project_visual_attention(source, 11, 12, clip_local=False)
    assert shot['windows'][0]['start_time_seconds'] == 11
    assert va.project_visual_attention(source, 14, 18)['status'] == 'NO_CLIP_INTERSECTION'
    assert source == before


def test_empty_primary_is_environment_and_multiple_primary_not_speaker_inference():
    for primary in ([], [A, B]):
        p, c = plan_clip([window(primary=primary, background=[])])
        projection = prepared(p, c)
        assert projection['status'] == 'VALID'
        text = va.render_visual_attention(projection)
        assert ('non-character composition' in text) == (primary == [])
        assert 'exact_dialogue' not in text
        assert 'do not freeze or remove it' in text
        assert projection['windows'][0]['primary_subjects'] == primary


def test_subject_mapping_uses_existing_order_without_picture_dependency():
    p, c = plan_clip()
    projection = prepared(p, c)
    assert {x['character_id']: x['subject'] for x in projection['characters']} == {A: '<Subject 2>', B: '<Subject 1>'}
    assert projection['windows'][0]['background_motion_subjects'] == [B]
    assert 'Jun approaches' in p['transitions'][0]['transition_description']
    p['visual_attention']['windows'][0]['primary_subjects'] = [C]
    assert prepared(p, c)['status'] == 'FALLBACK_INVALID'  # Kato is not in the owned state's visible closure.


def test_wrong_physical_identity_does_not_guess_another_subject():
    p, c = plan_clip()
    manifest = {'references': [{'kind': 'CHARACTER_IDENTITY', 'source_name': 'Mira', 'source_id': C}]}
    assert prepared(p, c, manifest)['status'] == 'FALLBACK_INVALID'


def test_fingerprint_stability_and_scoped_semantic_changes():
    p, c = plan_clip(); first = prepared(p, c)['fingerprint']
    p['visual_attention']['windows'][0]['reason'] = 'different audit prose'
    p['visual_attention']['windows'].append(window(20, 21))
    assert prepared(p, c)['fingerprint'] == first
    p['visual_attention']['windows'].insert(0, window(1, 2))
    assert prepared(p, c)['windows'][0]['source_window_index'] == 1
    assert prepared(p, c)['fingerprint'] == first
    p['transitions'].append({'from_keyframe_index': 8, 'to_keyframe_index': 9, 'transition_description': 'unrelated'})
    assert prepared(p, c)['fingerprint'] == first
    p['transitions'][0]['transition_description'] += ' Slowly.'
    assert prepared(p, c)['fingerprint'] != first
    for field, value in [('primary_subjects', [B]), ('end_time_seconds', 13), ('background_motion_subjects', [])]:
        changed, clip = plan_clip(); changed['visual_attention']['windows'][0][field] = value
        assert prepared(changed, clip)['fingerprint'] != first


def test_handoff_subject_and_time_changes_invalidate():
    p, c = plan_clip([window(10, 14, [A, B], [], handoff={'from': [A], 'to': [B]})])
    first = prepared(p, c)['fingerprint']
    p['visual_attention']['windows'][0]['handoff'] = {'from': [B], 'to': [A]}
    assert prepared(p, c)['fingerprint'] != first


def test_existing_subject_order_change_invalidates_prompt_fingerprint():
    p, c = plan_clip(); first = prepared(p, c)['fingerprint']
    p['keyframes'][0]['description'] = 'Characters:\n- Mira: beside table\n- Jun: near doorway\nAction: Hands at rest.'
    assert prepared(p, c)['fingerprint'] != first


def test_cache_requires_versions_fingerprint_and_exact_unique_section():
    p, c = plan_clip(); projection = prepared(p, c)
    prompt = va.compile_visual_attention('summary:\nExisting body.', projection)
    metadata = va.prompt_projection_metadata(projection, prompt)
    assert va.reusable_attention_prompt(prompt, projection, metadata)
    assert not va.reusable_attention_prompt('old prompt', projection, metadata)
    assert not va.reusable_attention_prompt(prompt, projection, None)
    assert not va.reusable_attention_prompt(prompt + '\nvisual_attention_timeline:\nwrong', projection, metadata)
    assert not va.reusable_attention_prompt(prompt.replace('primary narrative', 'wrong narrative'), projection, metadata)
    assert not va.reusable_attention_prompt(prompt, projection, {**metadata, 'projection_version': 2})
    changed, clip = plan_clip([window(10, 13)])
    assert not va.reusable_attention_prompt(prompt, prepared(changed, clip), metadata)
    assert not va.reusable_attention_prompt(prompt, va.project_visual_attention(None, 10, 18))
    assert va.reusable_attention_prompt('old legacy body', va.project_visual_attention(None, 10, 18))


def test_api_legacy_and_worker_direct_metadata_share_cache_check():
    p, c = plan_clip(); c['prompt_text'] = 'old'
    assert video.get_semantic_clip_prompt(p, c) == ''
    projection = prepared(p, c); c['prompt_text'] = va.compile_visual_attention('summary:\nbody', projection)
    c['prompt_projection'] = va.prompt_projection_metadata(projection, c['prompt_text'])
    assert video.get_semantic_clip_prompt(p, c) == c['prompt_text']
    canonical = {k: v for k, v in c.items() if k not in {'prompt_text', 'prompt_projection'}}
    p['clips'] = [copy.deepcopy(c)]
    assert video.get_semantic_clip_prompt(p, canonical) == c['prompt_text']
    assert va.reusable_attention_prompt(c['prompt_text'], projection, c['prompt_projection'])
    assert video._get_reusable_video_prompt(p, projection) == c['prompt_text']
    p['clips'][0]['prompt_projection']['fingerprint'] = 'stale'
    assert video.get_semantic_clip_prompt(p, canonical) == ''
    assert video._get_reusable_video_prompt(p, projection) == ''


@pytest.mark.parametrize('skip_llm', [False, True])
def test_worker_cache_resolution_never_calls_llm_on_miss(monkeypatch, skip_llm):
    def forbidden(*args, **kwargs):
        pytest.fail('Cache resolution must not invoke an LLM or generation worker')
    monkeypatch.setattr(video, 'build_h3_video_prompt', forbidden)
    p, c = plan_clip(); projection = prepared(p, c)
    assert video.resolve_reusable_clip_prompt(p, c, {'prompt_text': 'old body'}, projection,
        skip_llm=skip_llm, clip_only=True) == ''
    prompt = va.compile_visual_attention('summary:\nbody', projection)
    metadata = {'prompt_text': prompt, 'prompt_projection': va.prompt_projection_metadata(projection, prompt)}
    assert video.resolve_reusable_clip_prompt(p, c, metadata, projection,
        skip_llm=skip_llm, clip_only=True) == prompt
    p['clips'] = [{**c, **metadata}]
    assert video.resolve_reusable_clip_prompt(p, c, {}, projection,
        skip_llm=True, clip_only=False) == prompt
    p['visual_attention'] = None
    inactive = prepared(p, c)
    assert video.resolve_reusable_clip_prompt(p, c, metadata, inactive,
        skip_llm=True, clip_only=True) == ''


@pytest.mark.parametrize('raw', [{'time_base': 'CLIP_SECONDS', 'windows': []},
                               {'version': 1, 'time_base': 'SHOT_SECONDS', 'character_catalog': [None], 'windows': []}])
def test_malformed_optional_authority_keeps_legacy_cache_safe(raw):
    p, c = plan_clip(); p['visual_attention'] = raw
    c['prompt_text'] = 'legacy body without attention'
    assert video.get_semantic_clip_prompt(p, c) == c['prompt_text']
    c['prompt_text'] = 'summary:\nbody\nvisual_attention_timeline:\nstale authority'
    assert video.get_semantic_clip_prompt(p, c) == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', [False, True])
async def test_actual_08_persistence_and_10_consumption_do_not_replan_attention(db_session, monkeypatch, invalid):
    from app.models.novel import Novel, Chapter, Character
    from app.models.shot import Shot
    from app.models.prompt_template import PromptTemplate
    from app.repositories import NovelRepository, ChapterRepository, ShotRepository, PromptTemplateRepository
    from app.schemas.shot import PlanVideoKeyframesRequest

    novel = Novel(title='attention authority test'); db_session.add(novel); db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='test'); db_session.add(chapter); db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, duration=24, description='Mira and Jun in a room.',
        characters='["Mira","Jun"]', props='[]', dialogues='[]', video_director_plan=json.dumps({'visual_attention': authority()}))
    db_session.add_all([shot, Character(id=A, novel_id=novel.id, name='Mira'), Character(id=B, novel_id=novel.id, name='Jun'),
        PromptTemplate(name='planner', type='keyframe_planner', template='fixture', is_system=True),
        PromptTemplate(name='transition', type='keyframe_transition', template='fixture', is_system=True)])
    db_session.commit(); calls = []
    response_attention = {'windows': [window(10, 14, ['missing-uuid'] if invalid else [A], [B])]}
    async def complete(**kwargs):
        calls.append(kwargs['task_type'])
        payload = json.loads(kwargs['user_content'].split('\n\n', 1)[1])
        if kwargs['task_type'] == 'keyframe_planner':
            assert {x['character_id'] for x in payload['character_catalog']} == {A, B}
            return {'success': True, 'content': json.dumps({'keyframes': [
                {'index': 1, 'time_seconds': 0, 'role': 'START', 'description': None, 'timed_visual_target': False},
                {**state(2, 14), 'timed_visual_target': False}], 'visual_attention': response_attention})}
        assert kwargs['task_type'] == 'keyframe_transition'
        assert not {'dialogue_timeline_source', 'dialogues', 'speaker'}.intersection(payload)
        if invalid:
            assert 'visual_attention' not in payload
        else:
            assert payload['visual_attention']['windows'][0]['primary_subjects'] == [A]
        return {'success': True, 'content': json.dumps({'transition_description': 'Jun approaches the table.',
            'visual_attention': {'windows': []}})}  # #10 has no authority to replace #08.
    monkeypatch.setattr(api, 'get_style', lambda *args, **kwargs: ('', None))
    result = await api.plan_video_keyframes(novel.id, chapter.id, shot.id, PlanVideoKeyframesRequest(force=True),
        db_session, NovelRepository(db_session), ChapterRepository(db_session), ShotRepository(db_session),
        PromptTemplateRepository(db_session), SimpleNamespace(chat_completion=complete))
    db_session.expire_all()
    persisted = json.loads(ShotRepository(db_session).get_by_id(shot.id).video_director_plan)
    assert result['success'] and calls == ['keyframe_planner', 'keyframe_transition']
    assert len(persisted['keyframes']) == 2 and len(persisted['transitions']) == 1
    assert 'visual_attention' not in persisted['transitions'][0]
    if invalid:
        assert persisted['visual_attention'] is None  # Old authority cleared, no attention retry.
        assert persisted['validation']['visual_attention']['status'] == 'FALLBACK_INVALID'
    else:
        assert persisted['visual_attention']['version'] == 1
        assert persisted['visual_attention']['time_base'] == 'SHOT_SECONDS'
        assert persisted['visual_attention']['windows'][0]['primary_subjects'] == [A]
        log = next(call for call in persisted['ai_calls'] if call['step'] == '10')
        assert log['parsed_result']['visual_attention_consumed']['windows'][0]['primary_subjects'] == [A]


def test_model_redefinition_replaced_once_without_touching_other_sections():
    p, c = plan_clip(); projection = prepared(p, c)
    body = 'summary:\nunchanged\nvisual_attention_timeline:\nmodel invented priority\ndetailed_description:\nunchanged movement'
    final = va.compile_visual_attention(body, projection)
    assert final.count('visual_attention_timeline:') == 1
    assert 'model invented' not in final
    assert 'summary:\nunchanged' in final and 'detailed_description:\nunchanged movement' in final
    assert va.compile_visual_attention(final, projection) == final


def test_subcentisecond_times_are_not_rounded_in_final_authority():
    p, c = plan_clip([window(10.001, 10.004)])
    assert '0.001–0.004s:' in va.render_visual_attention(prepared(p, c))


def test_execution_snapshot_passes_through_existing_list_and_detail_dto():
    from app.models.task import Task
    from app.services.task_service import TaskService
    p, c = plan_clip(); projection = prepared(p, c)
    prompt = va.compile_visual_attention('summary:\nbody', projection)
    snapshot = va.execution_attention_snapshot(projection, prompt)
    task = Task(id='attention-dto-fixture', type='shot_video', status='completed',
        metadata_json=json.dumps({'execution_scope': 'CLIP', 'execution_contract': {'visual_attention_snapshot': snapshot}}))
    listed = TaskService.format_task_list([task], {}, {}, {})[0]
    detailed = TaskService.format_task_detail(task)
    for result in (listed, detailed):
        assert result['clipExecution']['execution_contract']['visual_attention_snapshot'] == snapshot


def test_08_and_10_input_contract_actual_assembly():
    shot = SimpleNamespace(id='shot', index=2, duration=24, characters='["Mira","Jun"]',
        dialogues='[]', description='existing', video_description='', scene='room', props='[]', continuity_mode='CONTINUOUS_TAKE')
    payload = json.loads(api._build_keyframe_planner_user_content(shot, {}, attention_catalog=CAT).split('\n\n', 1)[1])
    assert payload['character_catalog'] == CAT
    assert payload['requirements']['output_top_level_keys'] == ['keyframes', 'visual_attention']
    p = authority([window(10, 14, [A, B], [], handoff={'from': [A], 'to': [B]})])
    attention = va.project_visual_attention(p, 11, 12, clip_local=False)
    text = api._build_keyframe_transition_user_content(shot, state(1, 11), state(2, 12), 1, visual_attention=attention)
    transition_payload = json.loads(text.split('\n\n', 1)[1])
    assert transition_payload['visual_attention']['windows'][0]['handoff_progress'] == {'start': .25, 'end': .5}
    assert not {'dialogue_timeline_source', 'speaker', 'dialogues'}.intersection(transition_payload)
    template = (Path(__file__).parents[1]/'prompt_templates'/'10_NovelFlow_KeyframeTransition_Planner_V1.txt').read_text()
    assert 'Camera motion may compensate' in template and 'do not redefine them' in template


@pytest.mark.parametrize('shape,step', [([state()], '11'),
    ([{**state(), 'role': 'START'}, {**state(3, 18), 'role': 'END'}], '12'),
    ([state(), state(3, 15), {**state(4, 18), 'role': 'END'}], '13')])
@pytest.mark.parametrize('capability', ['GENERATE', 'EXTEND', 'TEMPORAL_EXTEND'])
def test_actual_h3_builder_variants_consume_and_compile_attention(monkeypatch, shape, step, capability):
    p, c = plan_clip(); c.update(capability=capability, visual_state_indexes=[s['index'] for s in shape])
    p['keyframes'] = shape
    shot = SimpleNamespace(id='shot', index=2, chapter_id='chapter', duration=24, characters='["Mira","Jun"]',
        props='[]', dialogues='[]', description='', video_description='', scene='room', continuity_mode='CONTINUOUS_TAKE', video_director_plan=json.dumps(p))
    calls = []
    body = 'subject_definitions:\n<Subject 1> is Jun.\n<Subject 2> is Mira.\nsummary:\nPreserve the room.\ndetailed_description:\nJun approaches the table.\noverall_soundscape:\nRoom tone.'
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs); return {'success': True, 'content': body}
    monkeypatch.setattr(h3, 'LLMService', FakeLLM)
    monkeypatch.setattr(h3, 'resolve_prompt_template', lambda *_: SimpleNamespace(template='fixture template', name='fixture'))
    prompt = asyncio.run(h3.build_h3_video_prompt(db=SimpleNamespace(commit=lambda: None), novel=SimpleNamespace(id='novel'),
        shot=shot, selected_mode='SINGLE_FRAME', clip=c, workflow_capability={}, workflow_type='frozen', workflow_name='frozen',
        start_image_url=None, keyframes=shape, transitions=p['transitions'], clip_dialogues=[], reference_images=[],
        video_reference_manifest={'references': []}, previous_av_present=capability != 'GENERATE'))
    request = json.loads(calls[0]['user_content'].split('\n\n', 1)[1])
    assert 'visual_attention_timeline' in request
    assert prompt.endswith(va.render_visual_attention(prepared(p, c)))
    assert prompt.count('visual_attention_timeline:') == 1
    log = json.loads(shot.video_director_plan)['ai_calls'][-1]
    assert log['step'] == step and log['response'] == body
    assert log['parsed_result']['visual_attention']['stage'] == 'PROMPTED'
    assert 'dialogue_timeline:' in prompt


def test_execution_snapshot_all_operations_and_temporal_domain_unchanged():
    p, c = plan_clip(); p['clip_plan_revision'] = 1
    p['keyframes'][0].update(image_url='/kf2.png', requirement='EXECUTION_REQUIRED')
    shot = SimpleNamespace(id='shot', duration=24, characters='["Mira","Jun"]', image_url='/start.png')
    previous = {'clip_index': 1, 'clip_plan_revision': 1, 'generated_by_task_id': 'task', 'result_url': '/c1.mp4'}
    c.update(previous_clip_index=1, requires_temporal_control=False)
    for capability in ('GENERATE', 'EXTEND', 'TEMPORAL_EXTEND'):
        clip = {**c, 'capability': capability}
        if capability == 'TEMPORAL_EXTEND':
            clip['requires_temporal_control'] = True
            result = compile_temporal_extend_clip(shot, p, clip, 1, previous,
                [{'anchor_id': 'KF2', 'time_seconds': 2, 'image_url': '/kf2.png', 'source': {'keyframe_index': 2}}])
        elif capability == 'EXTEND': result = compile_extend_clip(shot, p, clip, 1, previous)
        else: result = compile_generate_clip(shot, p, clip, 1)
        contract = result['execution_contract']
        assert contract['visual_attention_snapshot']['stage'] == 'PROJECTED'
        assert contract['visual_attention_snapshot']['program_owned_section_sha256'] is None
        if capability != 'GENERATE': assert contract['previous_clip']['result_url'] == '/c1.mp4'
        if capability == 'TEMPORAL_EXTEND':
            assert contract['visual_attention_snapshot']['temporal_times'][0]['frame_position'] == contract['temporal_anchor_manifest']['anchors'][0]['frame_position']
        no_attention = {k: v for k, v in p.items() if k != 'visual_attention'}
        if capability == 'TEMPORAL_EXTEND': control = compile_temporal_extend_clip(shot, no_attention, clip, 1, previous,
            [{'anchor_id': 'KF2', 'time_seconds': 2, 'image_url': '/kf2.png', 'source': {'keyframe_index': 2}}])
        elif capability == 'EXTEND': control = compile_extend_clip(shot, no_attention, clip, 1, previous)
        else: control = compile_generate_clip(shot, no_attention, clip, 1)
        assert result['video_reference_manifest'] == control['video_reference_manifest']
        assert {k:v for k,v in contract.items() if k != 'visual_attention_snapshot'} == control['execution_contract']
