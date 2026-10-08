"""Attention-only ownership, persistence and downstream freshness through formal entry points."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.api import shots as api
from app.models.novel import Novel, Chapter, Character
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.prompt_template import PromptTemplate
from app.repositories import NovelRepository, ChapterRepository, ShotRepository, PromptTemplateRepository, TaskRepository
from app.schemas.shot import PlanVideoKeyframesRequest, PlanVideoTransitionsRequest
from app.services import visual_attention as va, shot_video_service as video, video_director_ai as h3

A = '10000000-0000-0000-0000-000000000001'
B = '10000000-0000-0000-0000-000000000002'
CAT = [{'character_id': A, 'character_name': 'Mira'}, {'character_id': B, 'character_name': 'Jun'}]


def response(start=1, end=6, primary=A):
    return {'visual_attention': {'windows': [{'start_time_seconds': start, 'end_time_seconds': end,
        'primary_subjects': [primary], 'background_motion_subjects': [B if primary == A else A]}]}}


def plan_fixture():
    states = [
        {'index': 1, 'role': 'START', 'time_seconds': 0, 'description': None, 'timed_visual_target': False},
        {'index': 2, 'role': 'INTERMEDIATE', 'time_seconds': 6,
         'description': 'Scene: room\nCharacters:\n- Mira: by the window\n- Jun: at the table\nAction: both settled',
         'timed_visual_target': True, 'presence': ['Mira', 'Jun'], 'blocking': {'Mira': 'window'},
         'image_url': '/api/files/kf2.png', 'image_task_id': 'image-task', 'provenance': {'state_index': 2}},
        {'index': 3, 'role': 'END', 'time_seconds': 12,
         'description': 'Scene: room\nCharacters:\n- Mira: seated\n- Jun: at the table\nAction: both settled',
         'timed_visual_target': False},
    ]
    transitions = [{'segment_index': i, 'from_keyframe_index': i, 'to_keyframe_index': i + 1,
        'start_time': (i - 1) * 6, 'end_time': i * 6, 'transition_description': 'Mira approaches the chair.'}
        for i in [1, 2]]
    return {'canonical_visual_plan': True, 'keyframes': states, 'transitions': transitions,
        'clip_plan_revision': 7, 'dialogue_timeline_source': [], 'dialogue_timeline_status': {'status': 'empty'},
        'validation': {'passed': True}, 'required_execution_images': [{'ready': True}],
        'clip_execution_readiness': {'ready': True},
        'temporal_anchors': [{'anchor_id': 'KF2', 'frame_position': 206, 'image_url': '/api/files/kf2.png',
                             'source': {'keyframe_index': 2}}],
        'clip_plan': [{'clip_index': i, 'start_time': (i - 1) * 6, 'end_time': i * 6,
            'visual_state_indexes': [i + 1], 'carry_in_state_index': i, 'execution_status': 'APPROVED',
            'video_url': f'/api/files/c{i}.mp4', 'generated_by_task_id': f'approved-c{i}',
            'previous_approved_video_url': '/api/files/previous.mp4', 'capability': 'EXTEND'} for i in [1, 2]],
        'ordinary_refs': [{'slot': 9, 'kind': 'CHARACTER_IDENTITY', 'source_id': A}],
        'physical_output': {'source': 'NATIVE_CONTINUITY_OUTPUT', 'frame_count': 532},
        'motion_ownership': {'actor': 'Jun'}, 'body_lifecycle': {'Jun': 'existing'},
        'assembly_status': 'COMPLETED', 'merged_video_url': '/api/files/final.mp4',
        'clips': [], 'ai_calls': []}


@pytest.fixture
def ctx(db_session):
    db = db_session
    novel = Novel(title='attention-only test'); db.add(novel); db.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='test'); db.add(chapter); db.flush()
    plan = plan_fixture()
    shot = Shot(chapter_id=chapter.id, index=2, duration=12, description='Mira and Jun in a room.',
        video_description='', characters='["Mira","Jun"]', scene='room', props='[]', dialogues='[]',
        continuity_mode='CONTINUOUS_TAKE', video_director_plan=json.dumps(plan), keyframes=json.dumps(plan['keyframes']),
        image_url='/api/files/start.png', image_task_id='start-image', video_url='/api/files/final.mp4',
        video_task_id='assembly', video_status='completed')
    db.add_all([shot, Character(id=A, novel_id=novel.id, name='Mira'), Character(id=B, novel_id=novel.id, name='Jun'),
        PromptTemplate(name='attention', type='visual_attention_replan', template='attention-system', is_system=True),
        PromptTemplate(name='full', type='keyframe_planner', template='full-system', is_system=True),
        PromptTemplate(name='transition', type='keyframe_transition', template='transition-system', is_system=True)])
    db.flush()
    historical = Task(id='approved-c1', name='approved', type='shot_video', status='completed', shot_id=shot.id,
        prompt_text='historical prompt', result_url='/api/files/c1.mp4',
        metadata_json=json.dumps({'execution_scope': 'CLIP', 'clip_plan_revision': 7, 'clip_index': 1,
            'approval_status': 'APPROVED', 'execution_contract': {'visual_attention_snapshot': {'status': 'ABSENT'}}}))
    db.add(historical); db.commit()
    return SimpleNamespace(db=db, novel=novel, chapter=chapter, shot=shot, historical=historical,
        repos=(NovelRepository(db), ChapterRepository(db), ShotRepository(db), PromptTemplateRepository(db)))


def persist(ctx, plan):
    ctx.shot.video_director_plan = json.dumps(plan); ctx.db.commit()


def read(ctx):
    ctx.db.refresh(ctx.shot)
    return json.loads(ctx.shot.video_director_plan)


async def replan(ctx, output=None, mutate=None, success=True):
    calls = []
    async def complete(**kwargs):
        calls.append(kwargs)
        if mutate:
            mutate()
        return {'success': success, 'content': json.dumps(response() if output is None else output),
                'error': 'HTTP 502' if not success else None}
    llm = SimpleNamespace(chat_completion=complete)
    result = await api.plan_video_keyframes(ctx.novel.id, ctx.chapter.id, ctx.shot.id,
        PlanVideoKeyframesRequest(operation='ATTENTION_REPLAN'), ctx.db, *ctx.repos, llm)
    return result['data'], calls


@pytest.mark.asyncio
async def test_attention_only_persistence_preserves_all_states_and_assets(ctx, monkeypatch):
    before = read(ctx); image_fields = (ctx.shot.keyframes, ctx.shot.image_url, ctx.shot.image_task_id,
        ctx.shot.video_url, ctx.shot.video_task_id, ctx.shot.video_status)
    task_snapshot = (ctx.historical.prompt_text, ctx.historical.metadata_json, ctx.historical.status)
    def forbidden(*args, **kwargs):
        raise AssertionError('FULL replacement / auto #10 forbidden')
    monkeypatch.setattr(api, '_plan_keyframe_transitions', forbidden)
    monkeypatch.setattr(api, 'invalidate_downstream_for_canonical_visual_plan_replacement', forbidden)
    after, calls = await replan(ctx)
    assert len(calls) == 1 and calls[0]['task_type'] == 'keyframe_planner'
    assert after['visual_attention']['version'] == 1 and after['visual_attention']['time_base'] == 'SHOT_SECONDS'
    for key in before.keys() - {'validation', 'ai_calls', 'visual_attention'}:
        assert after[key] == before[key], key
    assert (ctx.shot.keyframes, ctx.shot.image_url, ctx.shot.image_task_id, ctx.shot.video_url,
        ctx.shot.video_task_id, ctx.shot.video_status) == image_fields
    ctx.db.refresh(ctx.historical)
    assert (ctx.historical.prompt_text, ctx.historical.metadata_json, ctx.historical.status) == task_snapshot
    payload = json.loads(calls[0]['user_content'].split('\n\n', 1)[1])
    assert payload['existing_canonical_visual_states'][1]['description'] == before['keyframes'][1]['description']
    assert payload['existing_canonical_visual_states'][1]['presence'] == ['Mira', 'Jun']
    assert payload['existing_canonical_visual_states'][1]['blocking'] == {'Mira': 'window'}
    assert payload['existing_canonical_visual_states'][1]['timed_visual_target'] is True
    assert not {'image_url', 'image_task_id', 'provenance'}.intersection(payload['existing_canonical_visual_states'][1])
    assert payload['existing_canonical_transitions'] == before['transitions']
    assert not {'temporal_anchors', 'clip_plan', 'references', 'frame_position'}.intersection(payload)
    assert va.stale_attention_edges(after) == {(1, 2)}
    assert after['ai_calls'][-1]['parsed_result']['source_input_sha256']


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['keyframes', 'transitions', 'clip_plan', 'motion_ownership', 'body_lifecycle', 'unexpected'])
async def test_extra_top_level_ownership_fails_without_stripping(ctx, field):
    old = read(ctx); old['visual_attention'] = va.normalize_visual_attention(response()['visual_attention'], CAT, 12)['authority']
    persist(ctx, old)
    with pytest.raises(HTTPException) as e:
        await replan(ctx, {**response(), field: []})
    assert e.value.status_code == 400
    after = read(ctx)
    for key in old.keys() - {'ai_calls'}:
        assert after[key] == old[key]
    assert after['ai_calls'][-1]['status'] == 'error'
    assert ctx.shot.video_status == 'completed'


@pytest.mark.asyncio
@pytest.mark.parametrize('out', [{}, {'visual_attention': None}, {'visual_attention': {'windows': 'bad'}},
    response(primary='unknown'), response(start=-1), response(end=15)])
async def test_missing_invalid_uuid_window_fail_preserving_owner(ctx, out):
    before = read(ctx); before['visual_attention'] = va.normalize_visual_attention(response()['visual_attention'], CAT, 12)['authority']
    persist(ctx, before)
    with pytest.raises(HTTPException) as e:
        await replan(ctx, out)
    assert e.value.status_code == 400
    assert read(ctx)['visual_attention'] == before['visual_attention']
    assert read(ctx)['keyframes'] == before['keyframes']


@pytest.mark.asyncio
async def test_http_failure_not_optional_fallback_or_business_retry(ctx):
    before = read(ctx)
    with pytest.raises(HTTPException) as e:
        await replan(ctx, success=False)
    assert e.value.status_code == 500
    assert 'visual_attention' not in read(ctx)
    assert read(ctx)['keyframes'] == before['keyframes']
    assert ctx.shot.video_status == 'completed'
    assert len(read(ctx)['ai_calls']) == 1


@pytest.mark.asyncio
async def test_empty_is_explicit_clear_and_stale_edges_accumulate(ctx):
    first, _ = await replan(ctx)
    second, _ = await replan(ctx, response(start=7, end=11))
    assert va.stale_attention_edges(second) == {(1, 2), (2, 3)}
    third, _ = await replan(ctx, {'visual_attention': {'windows': []}})
    assert third['visual_attention']['windows'] == []
    assert third['validation']['visual_attention']['status'] == 'EMPTY'
    assert va.stale_attention_edges(third) == {(1, 2), (2, 3)}
    assert third['clip_plan'] == first['clip_plan']


@pytest.mark.asyncio
async def test_same_effective_input_and_absent_empty_do_not_create_stale(ctx):
    empty, _ = await replan(ctx, {'visual_attention': {'windows': []}})
    assert not va.stale_attention_edges(empty)
    before, _ = await replan(ctx)
    before['validation']['visual_attention']['stale_transition_edges'] = []
    persist(ctx, before)
    same, _ = await replan(ctx)
    assert not va.stale_attention_edges(same)


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['state', 'dialogue', 'catalog', 'template', 'duration', 'attention'])
async def test_source_change_during_await_conflicts_without_overwriting(ctx, field):
    def mutate():
        p = read(ctx)
        if field == 'state': p['keyframes'][1]['description'] = 'new canonical state'
        elif field == 'dialogue': ctx.shot.dialogues = '[{"character_name":"Mira","text":"new text"}]'
        elif field == 'catalog': ctx.db.query(Character).filter(Character.id == A).first().name = 'changed name'
        elif field == 'template': ctx.repos[-1].get_default_system_template('visual_attention_replan').template = 'new system'
        elif field == 'duration': ctx.shot.duration = 13
        elif field == 'attention': p['visual_attention'] = va.normalize_visual_attention(response(primary=B)['visual_attention'], CAT, 12)['authority']
        ctx.shot.video_director_plan = json.dumps(p); ctx.db.commit()
    with pytest.raises(HTTPException) as e:
        await replan(ctx, mutate=mutate)
    assert e.value.status_code == 409
    after = read(ctx)
    if field == 'state': assert after['keyframes'][1]['description'] == 'new canonical state'
    if field == 'attention': assert after['visual_attention']['windows'][0]['primary_subjects'] == [B]
    if field not in {'attention'}: assert 'visual_attention' not in after


@pytest.mark.asyncio
async def test_unrelated_concurrent_write_and_new_image_binding_preserved(ctx, db_engine):
    # Separate session models another request; the original Session identity map is stale.
    def mutate():
        with sessionmaker(bind=db_engine)() as other:
            s = other.get(Shot, ctx.shot.id); p = json.loads(s.video_director_plan)
            p['inspector_note'] = 'keep me'; p['ai_calls'].append({'step': 'local', 'response': 'keep log'})
            p['keyframes'][1]['image_url'] = '/api/files/new-image.png'
            s.video_director_plan = json.dumps(p); other.commit()
    after, _ = await replan(ctx, mutate=mutate)
    assert after['inspector_note'] == 'keep me'
    assert after['ai_calls'][0]['response'] == 'keep log'
    assert after['keyframes'][1]['image_url'] == '/api/files/new-image.png'


@pytest.mark.asyncio
async def test_affected_active_task_prevents_publish_but_other_clip_does_not(ctx):
    task = Task(name='active', type='shot_video', status='running', shot_id=ctx.shot.id,
        metadata_json=json.dumps({'execution_scope': 'CLIP', 'clip_plan_revision': 7, 'clip_index': 1}))
    ctx.db.add(task); ctx.db.commit()
    with pytest.raises(HTTPException) as e:
        await replan(ctx)
    assert e.value.status_code == 409 and 'visual_attention' not in read(ctx)
    task.metadata_json = json.dumps({'execution_scope': 'CLIP', 'clip_plan_revision': 7, 'clip_index': 2})
    ctx.db.commit()
    after, _ = await replan(ctx)
    assert after['visual_attention']['windows']


@pytest.mark.asyncio
async def test_without_canonical_states_does_not_fallback_full(ctx):
    before = read(ctx); before['canonical_visual_plan'] = False; persist(ctx, before)
    with pytest.raises(HTTPException) as e:
        await replan(ctx)
    assert e.value.status_code == 400
    assert read(ctx) == before


@pytest.mark.asyncio
async def test_explicit_refresh_selected_stale_edges_through_original_helper(ctx, monkeypatch):
    await replan(ctx)
    await replan(ctx, response(start=7, end=11))
    before = read(ctx); calls = []
    async def complete(**kwargs):
        calls.append(kwargs)
        payload = json.loads(kwargs['user_content'].split('\n\n', 1)[1])
        assert kwargs['task_type'] == 'keyframe_transition'
        assert payload['segment_index'] == 2
        assert payload['from_keyframe']['description'] == before['keyframes'][1]['description']
        assert payload['to_keyframe']['description'] == before['keyframes'][2]['description']
        assert payload['visual_attention']['windows'][0]['primary_subjects'] == [A]
        assert not {'dialogue_timeline_source', 'dialogues', 'speaker'}.intersection(payload)
        return {'success': True, 'content': json.dumps({'transition_description': 'The camera glides toward the table.',
            'visual_attention': {'windows': []}})}  # #10 cannot acquire ownership by returning it.
    monkeypatch.setattr(api, 'get_style', lambda *a: ('', None))
    result = await api.refresh_attention_transitions(ctx.novel.id, ctx.chapter.id, ctx.shot.id,
        PlanVideoTransitionsRequest(transition_edges=[(2, 3)]), ctx.db, *ctx.repos, SimpleNamespace(chat_completion=complete))
    after = result['data']
    assert len(calls) == 1
    assert after['transitions'][0] == before['transitions'][0]
    assert after['transitions'][1]['segment_index'] == 2
    assert after['transitions'][1]['transition_description'] == 'The camera glides toward the table.'
    assert 'visual_attention' not in after['transitions'][1]
    assert after['visual_attention'] == before['visual_attention']
    assert after['keyframes'] == before['keyframes'] and after['clip_plan'] == before['clip_plan']
    assert va.stale_attention_edges(after) == {(1, 2)}
    va.require_current_attention_transitions(after, after['clip_plan'][1])


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['http', 'wrong_edge', 'source_change'])
async def test_refresh_failure_preserves_stale_and_transitions(ctx, monkeypatch, failure):
    await replan(ctx); before = read(ctx)
    async def complete(**kwargs):
        if failure == 'source_change':
            p = read(ctx); p['visual_attention']['windows'][0]['primary_subjects'] = [B]
            p['visual_attention']['windows'][0]['background_motion_subjects'] = [A]; persist(ctx, p)
        return {'success': failure != 'http', 'error': '502', 'content': json.dumps({
            'transition_description': 'The camera glides.',
            **({'from_keyframe_index': 9} if failure == 'wrong_edge' else {})})}
    monkeypatch.setattr(api, 'get_style', lambda *a: ('', None))
    with pytest.raises(HTTPException):
        await api.refresh_attention_transitions(ctx.novel.id, ctx.chapter.id, ctx.shot.id,
            PlanVideoTransitionsRequest(), ctx.db, *ctx.repos, SimpleNamespace(chat_completion=complete))
    after = read(ctx)
    assert after['transitions'] == before['transitions']
    assert va.stale_attention_edges(after) == va.stale_attention_edges(before)
    if failure == 'source_change': assert after['visual_attention']['windows'][0]['primary_subjects'] == [B]


@pytest.mark.asyncio
async def test_partial_refresh_failure_does_not_publish_first_success(ctx, monkeypatch):
    await replan(ctx, response(start=1, end=11)); before = read(ctx); n = 0
    async def complete(**kwargs):
        nonlocal n; n += 1
        return {'success': n == 1, 'content': '{"transition_description":"The camera glides."}', 'error': 'failure'}
    monkeypatch.setattr(api, 'get_style', lambda *a: ('', None))
    with pytest.raises(HTTPException):
        await api.refresh_attention_transitions(ctx.novel.id, ctx.chapter.id, ctx.shot.id,
            PlanVideoTransitionsRequest(), ctx.db, *ctx.repos, SimpleNamespace(chat_completion=complete))
    assert read(ctx)['transitions'] == before['transitions']
    assert va.stale_attention_edges(read(ctx)) == {(1, 2), (2, 3)}


def test_freshness_cache_and_historical_reads_are_separate():
    before = plan_fixture()
    before['visual_attention'] = va.normalize_visual_attention(response()['visual_attention'], CAT, 12)['authority']
    clip = before['clip_plan'][0]
    old = h3.prepare_clip_visual_attention(before, clip, ['Mira', 'Jun'])
    prompt = va.compile_visual_attention('summary:\nExisting visual state.', old)
    clip.update(prompt_text=prompt, prompt_projection=va.prompt_projection_metadata(old, prompt))
    updated = va.merge_attention_update(before, va.normalize_visual_attention(response(primary=B)['visual_attention'], CAT, 12), 12)
    current = h3.prepare_clip_visual_attention(updated, updated['clip_plan'][0], ['Mira', 'Jun'])
    assert not va.reusable_attention_prompt(prompt, current, clip['prompt_projection'])
    assert old['fingerprint'] != current['fingerprint']
    for call in [lambda: video.get_semantic_clip_prompt(updated, clip),
                 lambda: video.resolve_reusable_clip_prompt(updated, clip, {'prompt_text': prompt}, current, skip_llm=False, clip_only=True),
                 lambda: video._get_reusable_video_prompt(updated)]:
        with pytest.raises(ValueError, match='VISUAL_ATTENTION_TRANSITIONS_STALE'): call()
    va.require_current_attention_transitions(updated, updated['clip_plan'][1])  # unrelated clip
    # The pure historical projection and established Task list/detail DTO remain readable.
    from app.services.task_service import TaskService
    task = Task(id='historical', type='shot_video', status='completed', name='old',
        metadata_json=json.dumps({'execution_scope': 'CLIP', 'execution_contract': {'visual_attention_snapshot': old}}))
    assert TaskService.format_task_list([task], {}, {}, {})[0]['clipExecution']['execution_contract']['visual_attention_snapshot'] == old
    assert TaskService.format_task_detail(task)['clipExecution']['execution_contract']['visual_attention_snapshot'] == old
    from app.services.clip_execution_inspector_service import prompt_sections
    assert prompt_sections('summary:\nhistorical prompt', 'old')['summary']['text'] == 'historical prompt'


@pytest.mark.asyncio
async def test_direct_h3_cannot_bypass_freshness_even_with_offered_projection(monkeypatch):
    plan = va.merge_attention_update(plan_fixture(), va.normalize_visual_attention(response()['visual_attention'], CAT, 12), 12)
    def forbidden(*a, **kw): raise AssertionError('must stop before template/provider')
    monkeypatch.setattr(h3, 'resolve_prompt_template', forbidden)
    with pytest.raises(ValueError, match='VISUAL_ATTENTION_TRANSITIONS_STALE'):
        await h3.build_h3_video_prompt(db=None, novel=None, shot=SimpleNamespace(video_director_plan=json.dumps(plan)),
            selected_mode='MULTI_KEYFRAME', clip=plan['clip_plan'][0], workflow_capability={}, workflow_type='', workflow_name='',
            start_image_url=None, keyframes=[], transitions=[], clip_dialogues=[], reference_images=[], visual_attention={'status': 'ABSENT'})


@pytest.mark.asyncio
@pytest.mark.parametrize('skip', [False, True])
async def test_new_api_execution_rejected_before_task_creation(ctx, skip):
    await replan(ctx); before = ctx.db.query(Task).count()
    with pytest.raises(HTTPException) as e:
        await api.execute_semantic_clip(ctx.novel.id, ctx.chapter.id, ctx.shot.id, 1,
            api.SemanticClipGenerateRequest(clip_plan_revision=7, skip_llm_when_prompt_exists=skip),
            ctx.db, ctx.repos[0], ctx.repos[1], TaskRepository(ctx.db), ctx.repos[2])
    assert e.value.status_code == 409 and 'VISUAL_ATTENTION_TRANSITIONS_STALE' in e.value.detail
    assert ctx.db.query(Task).count() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('skip', [False, True])
async def test_worker_stops_before_llm_or_upload_even_for_reuse(ctx, monkeypatch, skip):
    await replan(ctx)
    before = read(ctx)
    workflow = Workflow(name='workflow fixture', type='multi_reference_video', workflow_json='{}', node_mapping='{}')
    task = Task(name='new worker task', type='shot_video', status='pending', shot_id=ctx.shot.id)
    ctx.db.add_all([workflow, task]); ctx.db.commit()
    def forbidden(*a, **kw): raise AssertionError('no LLM, upload or ComfyUI after stale owner')
    monkeypatch.setattr(video, 'SessionLocal', lambda: ctx.db)
    monkeypatch.setattr(ctx.db, 'close', lambda: None)
    monkeypatch.setattr(video, 'build_h3_video_prompt', forbidden)
    monkeypatch.setattr(video, 'ComfyUIService', forbidden)
    await video.generate_shot_video_task(task.id, ctx.novel.id, ctx.chapter.id, ctx.shot.index,
        workflow.id, '/api/files/start.png', clip_metadata={'execution_scope': 'CLIP', 'clip_index': 1, 'clip_plan_revision': 7,
            'capability': 'EXTEND', 'prompt_text': 'offered stale prompt'}, skip_llm_when_prompt_exists=skip)
    ctx.db.refresh(task)
    assert task.status == 'failed' and 'VISUAL_ATTENTION_TRANSITIONS_STALE' in task.error_message
    assert task.comfyui_prompt_id is None
    assert ctx.shot.video_status == 'completed'
    assert read(ctx)['clip_plan'] == before['clip_plan']
    assert ctx.historical.status == 'completed'


def test_source_renumbering_and_unrelated_windows_do_not_invalidate_effective_edge():
    plan = plan_fixture(); plan['visual_attention'] = va.normalize_visual_attention(response(start=7, end=11)['visual_attention'], CAT, 12)['authority']
    updated = deepcopy(plan['visual_attention'])
    updated['windows'].insert(0, response(start=1, end=2)['visual_attention']['windows'][0])
    assert va.changed_attention_edges(plan, updated, 12) == {(1, 2)}  # unchanged later source index shifted
    assert va.effective_transition_attention(plan['visual_attention'], 6, 12, 12) == va.effective_transition_attention(updated, 6, 12, 12)


def test_uuid_subject_resolution_is_independent_of_picture_slot():
    authority = va.normalize_visual_attention(response()['visual_attention'], CAT, 12)['authority']
    projection = va.project_visual_attention(authority, 0, 6, duration=12)
    mapped = va.resolve_subjects(projection, {'Mira': '<Subject 2>', 'Jun': '<Subject 1>'},
        {'references': [{'slot': 9, 'kind': 'CHARACTER_IDENTITY', 'source_name': 'Mira', 'source_id': A}]})
    assert mapped['status'] == 'VALID'
    assert mapped['characters'][0]['subject'] == '<Subject 2>'


def test_default_request_and_legacy_no_attention_remain_compatible():
    assert PlanVideoKeyframesRequest().operation == 'FULL_VISUAL_PLAN'
    plan = plan_fixture()
    va.require_current_attention_transitions(plan, plan['clip_plan'][0])
    assert video.get_semantic_clip_prompt(plan, plan['clip_plan'][0]) == ''
    assert va.CONTRACT_VERSION == va.PROJECTION_VERSION == 1


@pytest.mark.asyncio
async def test_explicit_refresh_restores_cache_and_does_not_call_unselected_edges(ctx, monkeypatch):
    before, _ = await replan(ctx)
    clip = before['clip_plan'][0]
    with pytest.raises(ValueError): video.get_semantic_clip_prompt(before, clip)
    calls = []
    async def complete(**kwargs):
        calls.append(kwargs)
        return {'success': True, 'content': '{"transition_description":"The camera glides toward the chair."}'}
    monkeypatch.setattr(api, 'get_style', lambda *a: ('', None))
    await api.refresh_attention_transitions(ctx.novel.id, ctx.chapter.id, ctx.shot.id,
        PlanVideoTransitionsRequest(), ctx.db, *ctx.repos, SimpleNamespace(chat_completion=complete))
    after = read(ctx); clip = after['clip_plan'][0]
    assert len(calls) == 1 and not va.stale_attention_edges(after)
    projection = h3.prepare_clip_visual_attention(after, clip, ['Mira', 'Jun'])
    final = va.compile_visual_attention('summary:\nRefreshed camera intent.', projection)
    clip['prompt_text'] = final; clip['prompt_projection'] = va.prompt_projection_metadata(projection, final)
    assert video.get_semantic_clip_prompt(after, clip) == final
    assert video.resolve_reusable_clip_prompt(after, clip, {}, projection, skip_llm=True, clip_only=True) == final
    assert after['keyframes'] == before['keyframes']


@pytest.mark.asyncio
async def test_refresh_source_conflict_preserves_unrelated_write(ctx, db_engine, monkeypatch):
    await replan(ctx)
    def mutate(**kwargs):
        with sessionmaker(bind=db_engine)() as other:
            shot = other.get(Shot, ctx.shot.id); p = json.loads(shot.video_director_plan)
            p['keyframes'][1]['description'] = 'new state during #10'
            p['inspector_note'] = 'concurrent note'; shot.video_director_plan = json.dumps(p); other.commit()
        return {'success': True, 'content': '{"transition_description":"The camera glides."}'}
    async def complete(**kwargs): return mutate(**kwargs)
    monkeypatch.setattr(api, 'get_style', lambda *a: ('', None))
    with pytest.raises(HTTPException) as e:
        await api.refresh_attention_transitions(ctx.novel.id, ctx.chapter.id, ctx.shot.id,
            PlanVideoTransitionsRequest(), ctx.db, *ctx.repos, SimpleNamespace(chat_completion=complete))
    assert e.value.status_code == 409
    assert read(ctx)['keyframes'][1]['description'] == 'new state during #10'
    assert read(ctx)['inspector_note'] == 'concurrent note'


def test_compare_and_swap_does_not_overwrite_last_moment_write(ctx, db_engine):
    prior = read(ctx)
    with sessionmaker(bind=db_engine)() as other:
        shot = other.get(Shot, ctx.shot.id); p = json.loads(shot.video_director_plan)
        p['newer_field'] = 'must survive'; shot.video_director_plan = json.dumps(p); other.commit()
    with pytest.raises(HTTPException) as e:
        api._commit_attention_plan(ctx.db, ctx.shot, {**prior, 'visual_attention': {}})
    assert e.value.status_code == 409
    assert read(ctx)['newer_field'] == 'must survive'
    assert 'visual_attention' not in read(ctx)


@pytest.mark.asyncio
async def test_official_dialogue_and_speaker_binding_are_read_only_inputs(ctx):
    dialogue = {'character_name': 'Mira', 'text': 'Look at the window.', 'type': 'character', 'order': 1}
    ctx.shot.dialogues = json.dumps([dialogue]); ctx.db.commit()
    p = read(ctx)
    p['dialogue_timeline_source'] = [{'id': 'D1', 'speaker': 'Mira', 'text': dialogue['text'],
        'start_time': 3.5, 'end_time': 5.5, 'estimated_duration': 2}]
    persist(ctx, p)
    after, calls = await replan(ctx)
    payload = json.loads(calls[0]['user_content'].split('\n\n', 1)[1])
    assert payload['dialogue_timeline_source'] == p['dialogue_timeline_source']
    assert payload['speaker_bindings'] == [{'dialogue_id': 'D1', 'speaker': 'Mira', 'character_id': A}]
    assert after['dialogue_timeline_source'] == p['dialogue_timeline_source']
    assert after['dialogue_timeline_status'] == p['dialogue_timeline_status']


@pytest.mark.asyncio
async def test_new_regeneration_rejected_before_task_creation(ctx):
    await replan(ctx); count = ctx.db.query(Task).count()
    with pytest.raises(HTTPException) as e:
        await api._regenerate_semantic_video_director_clip(ctx.novel.id, ctx.chapter.id, ctx.shot.id, 1,
            api.SemanticClipGenerateRequest(clip_plan_revision=7), ctx.db,
            ctx.repos[0], ctx.repos[1], TaskRepository(ctx.db), ctx.repos[2])
    assert e.value.status_code == 409 and 'VISUAL_ATTENTION_TRANSITIONS_STALE' in e.value.detail
    assert ctx.db.query(Task).count() == count


@pytest.mark.asyncio
async def test_full_cached_default_and_explicit_full_never_call_llm(ctx):
    async def forbidden(**kw): raise AssertionError('cached FULL does not call model')
    before = read(ctx)
    for request in [PlanVideoKeyframesRequest(), PlanVideoKeyframesRequest(operation='FULL_VISUAL_PLAN')]:
        result = await api.plan_video_keyframes(ctx.novel.id, ctx.chapter.id, ctx.shot.id,
            request, ctx.db, *ctx.repos, SimpleNamespace(chat_completion=forbidden))
        assert result['data']['keyframes'] == before['keyframes']
        assert result['data']['clip_plan'] == before['clip_plan']
        assert ctx.shot.video_url == '/api/files/final.mp4'


@pytest.mark.asyncio
async def test_active_clip_with_no_owned_transition_still_protects_its_h3_attention(ctx):
    p = read(ctx)
    p['clip_plan'][0]['visual_state_indexes'] = []
    p['clip_plan'][0]['carry_in_state_index'] = 1
    persist(ctx, p)
    ctx.db.add(Task(name='active inherited state', type='shot_video', status='running', shot_id=ctx.shot.id,
        metadata_json=json.dumps({'execution_scope': 'CLIP', 'clip_plan_revision': 7, 'clip_index': 1})))
    ctx.db.commit()
    with pytest.raises(HTTPException) as e:
        await replan(ctx)
    assert e.value.status_code == 409 and 'visual_attention' not in read(ctx)
