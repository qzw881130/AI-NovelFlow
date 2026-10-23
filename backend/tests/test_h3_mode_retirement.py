"""Removed prompt types and retired physical workflows stay out of new execution."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import shots, prompt_templates, workflows
from app.constants.workflow import RETIRED_H3_WORKFLOW_TYPES
from app.models.prompt_template import PromptTemplate
from app.models.workflow import Workflow
from app.models.task import Task
from app.services.prompt_template_service import PromptTemplateService
from app.services.workflow_service import WorkflowService
from app.services.task_service import TaskService
from app.services import video_director_ai as ai


@pytest.mark.asyncio
@pytest.mark.parametrize('states', [[], [{'index': 1, 'role': 'START'}],
    [{'index': 1, 'role': 'START'}, {'index': 2, 'role': 'END'}],
    [{'index': 1, 'role': 'START'}, {'index': 2}, {'index': 3, 'role': 'END'}]])
async def test_formal_builder_uses_13_override_for_every_control_shape(db_session, monkeypatch, states):
    current = PromptTemplate(id='current', name='13 override', type='h3_multi_keyframe_prompt', template='FORMAL 13', is_active=True)
    db_session.add(current); db_session.commit()
    novel = SimpleNamespace(id='novel', h3_multi_keyframe_prompt_template_id=current.id)
    shot = SimpleNamespace(id='shot', index=1, chapter_id='chapter', description='', video_description='',
        duration=8, continuity_mode='NORMAL', characters='[]', scene='', props='[]', dialogues='[]', video_director_plan='{}')
    calls = []
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            return {'success': True, 'content': 'summary:\nThe scene remains visible.\noverall_soundscape:\nRoom tone.'}
    monkeypatch.setattr(ai, 'LLMService', FakeLLM)
    await ai.build_h3_video_prompt(db_session, novel, shot, 'FIRST_LAST_FRAME',
        {'clip_index': 1, 'start_time': 0, 'end_time': 8, 'visual_state_indexes': [s['index'] for s in states]},
        {}, 'multi_reference_video', 'frozen', None, states, [], [], [], video_reference_manifest={'references': []})
    assert len(calls) == 1
    assert calls[0]['task_type'] == 'h3_multi_keyframe_prompt'
    assert calls[0]['system_prompt'].startswith('FORMAL 13')
    payload = json.loads(calls[0]['user_content'].split('\n\n', 1)[1])
    assert len(payload['visual_controls']) == len(states)
    assert json.loads(shot.video_director_plan)['ai_calls'][-1]['step'] == '13'


def test_removed_prompt_types_are_not_registered_and_existing_rows_are_deleted(db_session):
    removed_types = ['video_mode_recommender', 'h3_single_frame_prompt', 'h3_first_last_frame_prompt']
    rows = [PromptTemplate(id=f'{kind}-{origin}', name=kind, type=kind, template=kind,
                           is_system=(origin == 'system'), is_active=True)
            for kind in removed_types for origin in ('system', 'user')]
    db_session.add_all(rows); db_session.commit()
    service = PromptTemplateService(db_session)
    service.init_system_templates()
    catalog = prompt_templates.get_configurable_template_types()['data']
    assert all(kind not in catalog for kind in removed_types)
    assert all(db_session.get(PromptTemplate, f'{kind}-{origin}') is None
               for kind in removed_types for origin in ('system', 'user'))
    assert 'h3_multi_keyframe_prompt' in catalog


@pytest.mark.asyncio
async def test_old_batch_without_mode_does_not_call_removed_recommender(monkeypatch):
    shot = SimpleNamespace(id='shot', chapter_id='chapter', duration=5, description='',
                           video_description='', video_director_plan='{}')
    updates = []

    class FakeShotRepo:
        def __init__(self, db):
            pass

        def get_by_id(self, shot_id):
            return shot

        def update(self, current, **fields):
            updates.append(fields)

    monkeypatch.setattr(shots, 'ShotRepository', FakeShotRepo)
    monkeypatch.setattr(shots, 'WorkflowRepository',
                        lambda db: SimpleNamespace(get_active_by_type=lambda kind: None))
    monkeypatch.setattr(shots, 'NovelRepository', lambda db: SimpleNamespace())
    monkeypatch.setattr(shots, 'ChapterRepository', lambda db: SimpleNamespace())
    monkeypatch.setattr(shots, 'PromptTemplateRepository', lambda db: SimpleNamespace())
    monkeypatch.setattr(shots, 'LLMService', lambda: (_ for _ in ()).throw(AssertionError('unexpected LLM call')))

    mode = await shots._prepare_batch_video_details(None, None,
        SimpleNamespace(shot_id='shot', chapter_id='chapter'))
    assert mode == 'SINGLE_FRAME'
    assert updates[0]['video_director_plan']['selected_mode'] == mode


@pytest.mark.parametrize('kind', sorted(RETIRED_H3_WORKFLOW_TYPES))
def test_old_workflows_are_readable_but_not_selectable_or_retryable(db_session, kind):
    workflow = Workflow(id='old', name='arbitrary name', type=kind, workflow_json='{"frozen":true}', is_active=True)
    task = Task(id='history', name='historical video', type='shot_video', status='completed', workflow_id='old',
                result_url='/history.mp4', workflow_json='{"snapshot":true}', metadata_json='{}')
    db_session.add_all([workflow, task]); db_session.commit()
    service = WorkflowService(db_session)
    assert kind not in workflows.get_generation_workflow_types()['data']
    assert service.format_workflow_detail(workflow)['workflowJson'] == '{"frozen":true}'
    assert service.format_workflow_list([workflow])[0]['availableForNewTasks'] is False
    assert service.set_default_workflow(workflow.id)['status_code'] == 410
    assert TaskService(db_session).retry_task(task.id)['status_code'] == 410
    db_session.refresh(task); db_session.refresh(workflow)
    assert task.status == 'completed' and task.result_url == '/history.mp4'
    assert task.workflow_json == '{"snapshot":true}' and workflow.is_active


@pytest.mark.parametrize('kind', ['multi_reference_video', 'VIDEO_CONTINUATION', 'TEMPORAL_EXTEND'])
def test_current_physical_routes_still_available(kind):
    assert kind in workflows.get_generation_workflow_types()['data']
    workflow = Workflow(name='same name as an old workflow', type=kind, workflow_json='{}')
    assert WorkflowService.format_workflow_detail(workflow)['availableForNewTasks'] is True


def legacy_repos(plan=None):
    shot = SimpleNamespace(id='shot', chapter_id='chapter', index=1, image_url='/history.png',
        video_url='/history.mp4', video_director_plan=json.dumps(plan or {'selected_mode': 'SINGLE_FRAME'}))
    shot_repo = SimpleNamespace(get_by_id=lambda *_: shot)
    chapter_repo = SimpleNamespace(get_by_id=lambda *_: SimpleNamespace(id='chapter'))
    novel_repo = SimpleNamespace(get_by_id=lambda *_: SimpleNamespace(id='novel'))
    return shot, shot_repo, chapter_repo, novel_repo


def allow_isolated_preflight(monkeypatch):
    monkeypatch.setattr('app.api.config.get_or_create_config', lambda db: None)
    monkeypatch.setattr('app.services.generation_preflight.config_policy', lambda config: {})
    monkeypatch.setattr('app.services.generation_preflight.evaluate_batch',
                        lambda *args, **kwargs: {'ready': True})


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['shot', 'clip', 'clip_plan', 'batch', 'selection'])
async def test_legacy_entries_stop_before_tasks_llm_or_asset_mutation(entry, monkeypatch):
    shot, sr, cr, nr = legacy_repos()
    allow_isolated_preflight(monkeypatch)
    before = vars(shot).copy()
    # Empty collaborators deliberately fail if execution or persistence is attempted.
    empty = SimpleNamespace()
    with pytest.raises(HTTPException) as error:
        if entry == 'shot':
            await shots.generate_shot_video('novel','chapter','shot', shots.GenerateVideoRequest(),nr,cr,empty,empty,sr)
        elif entry == 'clip':
            await shots.generate_video_director_clip('novel','chapter','shot',1, shots.GenerateVideoDirectorClipRequest(),nr,cr,empty,empty,sr)
        elif entry == 'clip_plan':
            await shots.generate_clip_plan_video('novel','chapter','shot',empty,nr,sr)
        elif entry == 'batch':
            await shots.generate_shot_videos_batch('novel','chapter',shots.BatchShotVideoRequest(shot_ids=['shot'], auto_complete_details=False),empty,nr,cr,sr)
        else:
            await shots.save_video_director_plan('novel','chapter','shot',shots.SaveVideoDirectorPlanRequest(selected_mode='MULTI_KEYFRAME'),cr,sr)
    assert error.value.status_code == 410
    assert error.value.detail['code'] == 'LEGACY_H3_GENERATION_RETIRED'
    assert vars(shot) == before


@pytest.mark.asyncio
async def test_workflow_generation_list_filters_by_type_not_name():
    legacy = Workflow(id='old', name='多参考生视频', type='video', workflow_json='{}')
    current = Workflow(id='new', name='单帧历史名称', type='multi_reference_video', workflow_json='{}')
    repo = SimpleNamespace(list_all=lambda: [legacy, current])
    service = SimpleNamespace(load_default_workflows=lambda: None)
    history = await workflows.list_workflows(type=None, db=None, workflow_service=service, workflow_repo=repo)
    formal = await workflows.list_workflows(type=None, for_generation=True, db=None, workflow_service=service, workflow_repo=repo)
    assert [w['id'] for w in history['data']] == ['old', 'new']
    assert [w['id'] for w in formal['data']] == ['new']


def test_http_catalog_routes(client):
    templates = client.get('/api/prompt-templates/config-types').json()
    assert templates['success'] and 'h3_multi_keyframe_prompt' in templates['data']
    assert not {'video_mode_recommender', 'h3_single_frame_prompt', 'h3_first_last_frame_prompt'}.intersection(templates['data'])
    for kind in ('video_mode_recommender', 'h3_single_frame_prompt', 'h3_first_last_frame_prompt'):
        response = client.post('/api/prompt-templates/', json={
            'name': 'removed', 'template': 'removed', 'type': kind,
        })
        assert response.status_code == 400
    physical = client.get('/api/workflows/generation-types').json()
    assert physical['success'] and 'multi_reference_video' in physical['data']
    assert not RETIRED_H3_WORKFLOW_TYPES.intersection(physical['data'])


@pytest.mark.asyncio
async def test_semantic_clip_entry_remains_on_existing_execution_path(monkeypatch):
    plan = {'clip_plan_revision': 3, 'clip_plan': [{'clip_index': 1, 'capability': 'GENERATE'}]}
    shot,sr,cr,nr = legacy_repos(plan)
    sr.db = SimpleNamespace()
    captured = []
    async def execute(*args):
        captured.append(args)
        return {'success':True, 'data': {'taskId':'mock-only'}}
    monkeypatch.setattr(shots, 'execute_semantic_clip', execute)
    result = await shots.generate_video_director_clip('novel','chapter','shot',1,
        shots.GenerateVideoDirectorClipRequest(clip_plan_revision=3),nr,cr,SimpleNamespace(),SimpleNamespace(),sr)
    assert result['success'] and len(captured) == 1
    assert captured[0][4].clip_plan_revision == 3
    assert shot.video_director_plan == json.dumps(plan)


@pytest.mark.asyncio
async def test_batch_cannot_reintroduce_retired_semantic_capability(monkeypatch):
    shot,sr,cr,nr = legacy_repos({'clip_plan':[{'clip_index':1, 'capability':'SINGLE_FRAME'}]})
    allow_isolated_preflight(monkeypatch)
    with pytest.raises(HTTPException) as error:
        await shots.generate_shot_videos_batch('novel','chapter',shots.BatchShotVideoRequest(shot_ids=['shot']),SimpleNamespace(),nr,cr,sr)
    assert error.value.status_code == 410
