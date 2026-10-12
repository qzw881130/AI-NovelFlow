"""Regression cases found in the Shot 6 pre-generation review. No live I/O."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from sqlalchemy.orm import sessionmaker
from app.api import shots as api
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.shot import Shot
from app.services import business_events as events
from test_semantic_batch_scheduler import _fixture
from test_clip_result_recovery import execution
from app.services.clip_result_recovery import INTERRUPTED_CLIP_ERROR


@pytest.mark.asyncio
async def test_missing_reusable_prompt_creates_no_orphan_task(db_session, monkeypatch):
    novel,chapter,shot,parent,child=_fixture(db_session,capabilities=('GENERATE',))
    db_session.add(Workflow(id='mock-workflow',name='mock',type='multi_reference_video',is_active=True,workflow_json='{}'))
    db_session.commit()
    monkeypatch.setattr(api,'_require_attention_execution_freshness',lambda *args:None)
    monkeypatch.setattr(api,'resolve_clip_reference_resources',lambda *args:{})
    monkeypatch.setattr(api,'compile_generate_clip',lambda *args,**kwargs:{'execution_contract':{'artifact_kind':'CLIP_ONLY'},'video_reference_manifest':{'references':[]}})
    monkeypatch.setattr(api.TaskService,'validate_workflow_node_mapping',lambda *args:(True,''))
    monkeypatch.setattr(api,'resolve_canonical_dialogue_timeline',lambda *args:([],{}))
    monkeypatch.setattr(api,'assign_dialogues_to_clips',lambda *args:([{'clip_index':1,'dialogues':[]}],{'passed':True}))
    monkeypatch.setattr(api,'build_execution_intent_metadata',lambda *args:{})
    monkeypatch.setattr(api,'build_dialogue_visual_support_evidence',lambda *args,**kw:{})
    monkeypatch.setattr(api,'get_semantic_clip_prompt',lambda *args:'')
    enqueue=Mock();monkeypatch.setattr(api,'enqueue_shot_video_task',enqueue)
    before=db_session.query(Task).count()
    with pytest.raises(api.HTTPException,match='') as failure:
        await api.execute_semantic_clip(novel.id,chapter.id,shot.id,1,
            api.SemanticClipGenerateRequest(clip_plan_revision=3,skip_llm_when_prompt_exists=True),db_session,
            api.NovelRepository(db_session),api.ChapterRepository(db_session),api.TaskRepository(db_session),api.ShotRepository(db_session))
    assert failure.value.status_code==400
    assert db_session.query(Task).count()==before
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_final_clip_failure_updates_shot_without_removing_assets(db_session, monkeypatch):
    _,_,shot,parent,child=_fixture(db_session,capabilities=('GENERATE',))
    shot.video_status='pending';shot.video_url='/saved/previous-version.mp4'
    shot.video_task_id=child.id;db_session.commit()
    monkeypatch.setattr(api,'SessionLocal',sessionmaker(bind=db_session.get_bind()))
    async def failed(db,parent,child,shot):
        child.error_message='C1: required reference upload failed';db.commit()
        return 'failed'
    monkeypatch.setattr(api,'_run_semantic_shot_for_batch',failed)
    await api.run_shot_video_batch_task(parent.id)
    db_session.expire_all()
    assert db_session.get(Task,parent.id).status=='failed'
    assert db_session.get(Shot,shot.id).video_status=='failed'
    assert db_session.get(Shot,shot.id).video_url=='/saved/previous-version.mp4'


def test_failed_event_has_actual_reason_without_prompt_or_credentials():
    task=Task(id='test',type='shot_video',status='failed',name='C1',shot_id='s',
        error_message='REFERENCE_IMAGE_UPLOAD_FAILED: token=secret',
        prompt_text='DO NOT COPY CANONICAL PROMPT',
        metadata_json=json.dumps({'execution_scope':'CLIP','clip_index':1,'clip_id':'s:clip:1'}))
    code,payload,_,_=events.task_events(task)[0]
    assert code=='clip.generation.failed'
    assert 'REFERENCE_IMAGE_UPLOAD_FAILED' in payload['message']
    assert 'secret' not in payload['message']
    assert 'DO NOT COPY' not in json.dumps(payload)


@pytest.mark.asyncio
async def test_saved_clip_success_clears_stale_failure_but_keeps_task_history(execution, db_session):
    task, shot, _, service, _, _ = execution
    plan = json.loads(shot.video_director_plan)
    plan['clip_plan'][0]['error_message'] = INTERRUPTED_CLIP_ERROR
    shot.video_director_plan = json.dumps(plan)
    task.error_message = INTERRUPTED_CLIP_ERROR
    historical = Task(id='earlier-attempt', type='shot_video', name='Earlier failure',
                      status='failed', error_message=INTERRUPTED_CLIP_ERROR)
    db_session.add(historical)
    db_session.commit()
    task.updated_at = datetime.utcnow() - timedelta(minutes=2)
    db_session.commit()
    assert await service.reconcile_active_tasks([task]) == 1
    clip = json.loads(shot.video_director_plan)['clip_plan'][0]
    assert clip['execution_status'] == 'APPROVED'
    assert not clip.get('error_message')
    assert db_session.get(Task, historical.id).error_message == INTERRUPTED_CLIP_ERROR


@pytest.mark.asyncio
@pytest.mark.parametrize('reference_count', [0, 2, 5, 9])
async def test_mock_comfy_boundary_uses_final_prompt_and_ordered_references(reference_count):
    from app.services.comfyui.service import ComfyUIService
    from app.services.comfyui.workflows import WorkflowBuilder
    fixtures = Path(__file__).parent / 'fixtures'
    frozen = json.loads((fixtures / 'h3_continuation_workflow.json').read_text())
    original = frozen['workflow_json']
    mapping = json.loads(frozen['node_mapping'])
    final_prompt = json.loads((fixtures / 'h3_v5_approved_c1.json').read_text())['output']['optimized_prompt']
    client = SimpleNamespace(
        upload_video=AsyncMock(return_value={'success': True, 'filename': 'approved-native-cumulative.mp4'}),
        upload_image=AsyncMock(side_effect=lambda path: {'success': True, 'filename': Path(path).name}),
        queue_prompt=AsyncMock(return_value={'success': True, 'prompt_id': 'mock-only-receipt'}),
        wait_for_result=AsyncMock(return_value={'success': True, 'video_url': 'mock://native-output.mp4'}),
    )
    # Do not construct the product network client or load runtime credentials.
    service = object.__new__(ComfyUIService)
    service.client, service.builder = client, WorkflowBuilder()
    callback = Mock()
    paths = [f'/mock/reference-{i}.png' for i in range(1, reference_count + 1)]
    result = await service.generate_video_continuation_with_workflow(
        final_prompt, original, mapping, '/mock/approved-cumulative.mp4', 18.0,
        'isolated-mock-output', reference_image_paths=paths,
        on_prompt_queued=callback, require_native_output=True,
    )
    assert result['success']
    graph = result['submitted_workflow']
    assert graph[mapping['prompt_node_id']]['inputs']['prompt'] == final_prompt
    assert graph[mapping['duration_seconds_node_id']]['inputs']['value'] == 18.0
    assert graph[mapping['load_video_node_id']]['inputs']['video'] == 'approved-native-cumulative.mp4'
    assert graph['65']['inputs']['context_frames'] == 39
    assert graph['65']['inputs']['video_overlap_frames'] == 39
    assert graph['65']['inputs']['source_fps'] == 24
    ref_inputs = graph[mapping['reference_to_video_node_id']]['inputs']
    for i in range(9):
        node_id = mapping[f'load_image_node_{i+1}']
        if i < reference_count:
            assert ref_inputs[f'ref_images.ref_image_{i}'] == [node_id, 0]
            assert graph[node_id]['inputs']['image'] == Path(paths[i]).name
        else:
            assert f'ref_images.ref_image_{i}' not in ref_inputs and node_id not in graph
    assert graph['3'] == json.loads(original)['3']  # sampler/seed unchanged
    assert frozen['workflow_json'] == original
    client.queue_prompt.assert_awaited_once()
    callback.assert_called_once_with('mock-only-receipt', graph)
    client.wait_for_result.assert_awaited_once()
    assert client.wait_for_result.call_args.args[2] == '65'
    assert client.wait_for_result.call_args.kwargs['strict_output_node'] is True
