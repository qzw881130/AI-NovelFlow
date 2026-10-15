"""Retire business entries without touching workflow execution or historical rows."""
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
    old = PromptTemplate(id='legacy', name='legacy override', type='h3_single_frame_prompt', template='DO NOT USE', is_active=True)
    current = PromptTemplate(id='current', name='13 override', type='h3_multi_keyframe_prompt', template='FORMAL 13', is_active=True)
    db_session.add_all([old, current]); db_session.commit()
    novel = SimpleNamespace(id='novel', h3_single_frame_prompt_template_id=old.id,
        h3_first_last_frame_prompt_template_id=old.id, h3_multi_keyframe_prompt_template_id=current.id)
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
    assert db_session.get(PromptTemplate, 'legacy').template == 'DO NOT USE'


def test_configuration_catalog_hides_11_12_but_history_remains(db_session):
    rows = [PromptTemplate(id=kind, name=kind, type=kind, template=kind, is_system=True, is_active=True)
        for kind in ['h3_single_frame_prompt', 'h3_first_last_frame_prompt', 'h3_multi_keyframe_prompt',
                     'h3_execution_optimizer_prompt', 'h3_preflight_repair_prompt']]
    db_session.add_all(rows); db_session.commit()
    service = PromptTemplateService(db_session)
    catalog = prompt_templates.get_configurable_template_types()['data']
    for row in rows[:2]:
        assert row.type not in catalog
        assert prompt_templates.list_prompt_templates(type=row.type, service=service)['data'] == []
        assert prompt_templates.get_prompt_template(row.id, service)['data']['template'] == row.template
        assert prompt_templates.list_prompt_templates(type=row.type, include_retired=True, service=service)['data'][0]['id'] == row.id
        assert row.is_active  # no migration or historical mutation
    assert all(row.type in catalog for row in rows[2:])
    assert db_session.query(PromptTemplate).count() == 5


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


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['recommend', 'shot', 'clip', 'clip_plan', 'batch', 'selection'])
async def test_legacy_entries_stop_before_tasks_llm_or_asset_mutation(entry):
    shot, sr, cr, nr = legacy_repos()
    before = vars(shot).copy()
    # Empty collaborators deliberately fail if execution or persistence is attempted.
    empty = SimpleNamespace()
    with pytest.raises(HTTPException) as error:
        if entry == 'recommend':
            await shots.recommend_video_mode('novel','chapter','shot', shots.RecommendVideoModeRequest(), empty,nr,cr,sr,empty,empty,empty)
        elif entry == 'shot':
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
async def test_canonical_recommend_remains_read_only_without_07():
    plan = {'canonical_visual_plan': True, 'keyframes': [{'index':1}], 'clip_plan': []}
    shot,sr,cr,nr = legacy_repos(plan)
    before = shot.video_director_plan
    empty = SimpleNamespace()
    result = await shots.recommend_video_mode('novel','chapter','shot', shots.RecommendVideoModeRequest(force=True),empty,nr,cr,sr,empty,empty,empty)
    assert result['data'] == plan and shot.video_director_plan == before


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
    assert 'h3_single_frame_prompt' not in templates['data']
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
async def test_batch_cannot_reintroduce_retired_semantic_capability():
    shot,sr,cr,nr = legacy_repos({'clip_plan':[{'clip_index':1, 'capability':'SINGLE_FRAME'}]})
    with pytest.raises(HTTPException) as error:
        await shots.generate_shot_videos_batch('novel','chapter',shots.BatchShotVideoRequest(shot_ids=['shot']),SimpleNamespace(),nr,cr,sr)
    assert error.value.status_code == 410
