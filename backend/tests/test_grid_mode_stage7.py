"""Queue persistence, failure boundaries, and submitted-prompt recovery."""

import asyncio
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.models.background_job import BackgroundJob
from app.models.novel import Chapter, Novel
from app.models.system_config import SystemConfig
from app.models.shot import Shot
from app.models.task import Task
from app.schemas.grid_shot import GridPanel, GridShotData, dump_grid_data, load_grid_data
from app.services.background_workers import worker_manager
from app.services.file_storage import file_storage
from app.services.grid_pipeline import GridPipeline, GridPipelineError
from app.services.grid_tasks import enqueue_grid_job, reconcile_grid_batches, run_grid_job
from app.services.task_service import TaskService


@pytest.mark.parametrize('auto_approve', [False, True])
def test_grid_chapter_merge_supports_nameplate_preview(client, db_session, monkeypatch,
                                                       tmp_path, auto_approve):
    from app.api import shots as shots_api
    from app.services import grid_pipeline

    novel, chapter = grid_novel_with_chapter(db_session)
    source = tmp_path / 'shot.mp4'
    source.write_bytes(b'raw shot')
    shot = Shot(chapter_id=chapter.id, index=1, characters=json.dumps(['甲']),
                video_url='/api/files/shot.mp4')
    db_session.add(shot)
    config = db_session.get(SystemConfig, 'default')
    if not config:
        config = SystemConfig(id='default')
        db_session.add(config)
    config.nameplate_preview_mode = 'chapter_first'
    config.auto_approve_first_appearance_names = auto_approve
    task = Task(type='grid_chapter_merge', status='running', novel_id=novel.id,
                chapter_id=chapter.id, name='合并章回', metadata_json='{"grid_step":"chapter_merge"}')
    db_session.add(task)
    db_session.commit()

    monkeypatch.setattr(grid_pipeline.file_storage, '_get_story_dir', lambda _: tmp_path)
    local_path = lambda url: str(tmp_path / url.removeprefix('/api/files/'))
    monkeypatch.setattr(grid_pipeline, 'url_to_local_path', local_path)
    monkeypatch.setattr(shots_api, 'url_to_local_path', local_path)
    monkeypatch.setattr(grid_pipeline, 'local_path_to_url',
                        lambda path: '/api/files/' + Path(path).relative_to(tmp_path).as_posix())

    async def fake_merge(paths, output):
        assert paths == [str(source)]
        with open(output, 'wb') as handle:
            handle.write(b'raw chapter')
        return {'success': True}

    async def fake_events(db, novel_id, chapter_id, segments, output_size=None, mode=None,
                          use_distractor_references=False):
        assert mode == 'chapter_first'
        assert use_distractor_references is True
        assert segments == [{'kind': 'shot', 'key': 1, 'path': str(source)}]
        return ([{'start': 0.0, 'end': 1.0, 'name': '甲'}], [])

    async def fake_render(raw, preview, events):
        assert raw.read_bytes() == b'raw chapter'
        preview.write_bytes(b'with nameplate')

    monkeypatch.setattr(grid_pipeline.file_storage, 'merge_videos', fake_merge)
    monkeypatch.setattr(grid_pipeline, 'probe_nameplate_video', lambda _: (640, 360, 2.0))
    monkeypatch.setattr(grid_pipeline, 'build_nameplate_events', fake_events)
    monkeypatch.setattr(grid_pipeline, 'render_first_appearance_nameplates', fake_render)

    result = asyncio.run(GridPipeline(db_session).merge_chapter(novel, chapter, task=task))
    metadata = json.loads(task.metadata_json)
    assert metadata['nameplate_status'] == ('approved' if auto_approve else 'pending_confirmation')
    assert metadata['nameplate_auto_approved'] is auto_approve
    assert metadata['nameplate_raw_url'] != metadata['nameplate_preview_url']
    assert result == (metadata['nameplate_preview_url'] if auto_approve else metadata['nameplate_raw_url'])
    assert db_session.get(Chapter, chapter.id).final_video == result
    assert Path(local_path(metadata['nameplate_raw_url'])).read_bytes() == b'raw chapter'
    assert Path(local_path(metadata['nameplate_preview_url'])).read_bytes() == b'with nameplate'
    listed = client.get('/api/tasks/?summary=true').json()['data']
    projection = next(item for item in listed if item['id'] == task.id)
    assert projection['nameplatePreview']['status'] == metadata['nameplate_status']
    if not auto_approve:
        approved = asyncio.run(shots_api.approve_chapter_nameplate_preview(
            novel.id, chapter.id, task.id, db_session))
        assert approved['video_url'] == metadata['nameplate_preview_url']
        assert db_session.get(Chapter, chapter.id).final_video == approved['video_url']


def hold_grid_worker(monkeypatch, db_engine):
    class HoldWorker:
        def enqueue(self, request, *, db):
            worker_manager.persist(request, 'grid', db=db)
    monkeypatch.setattr(worker_manager, 'worker', lambda name: HoldWorker())
    monkeypatch.setattr(worker_manager, '_session_factory', lambda: Session(db_engine))


def grid_novel_with_chapter(db_session):
    novel = Novel(title='宫格队列', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='黄昏投宿', content='门前交谈。')
    db_session.add(chapter)
    db_session.commit()
    return novel, chapter


def ready_shot(db_session, chapter, index):
    shot = Shot(chapter_id=chapter.id, index=index, description=f'Shot {index}', duration=8)
    grid = GridShotData(revision=1, layout='2x2', seed=index, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat=f'Beat {i}', camera='中景') for i in range(1, 5)],
                        board_prompt=f'Board {index}')
    shot.grid_data = dump_grid_data(grid)
    db_session.add(shot)
    db_session.commit()
    return shot


def test_grid_plan_is_persistent_and_does_not_run_in_request(db_session, db_engine, monkeypatch):
    hold_grid_worker(monkeypatch, db_engine)
    novel, chapter = grid_novel_with_chapter(db_session)
    task = enqueue_grid_job(db_session, novel, chapter, None, 'chapter_plan')
    assert task.status == 'pending'
    assert db_session.query(Shot).filter(Shot.chapter_id == chapter.id).count() == 0
    job = db_session.query(BackgroundJob).filter(BackgroundJob.task_id == task.id).one()
    assert job.status == 'queued'
    assert job.handler == 'app.services.grid_tasks:run_grid_job'

    async def fake_ask(self, novel, chapter, shot, kind, payload, **kwargs):
        return {'shots': [{'title': '投宿', 'description': '抵达村口', 'duration': 8,
                           'characters': [], 'scene': '', 'props': [], 'dialogues': []}]}, 'template'
    monkeypatch.setattr(GridPipeline, '_ask', fake_ask)
    asyncio.run(worker_manager.run_persisted(job.id))
    db_session.expire_all()
    assert db_session.get(Task, task.id).status == 'completed'
    assert db_session.get(BackgroundJob, job.id).status == 'completed'
    assert db_session.query(Shot).filter(Shot.chapter_id == chapter.id).count() == 1
    asyncio.run(worker_manager.run_persisted(job.id))
    assert db_session.query(Shot).filter(Shot.chapter_id == chapter.id).count() == 1


def test_grid_batch_stops_after_first_failure(client, db_session, db_engine, monkeypatch):
    hold_grid_worker(monkeypatch, db_engine)
    novel, chapter = grid_novel_with_chapter(db_session)
    ready_shot(db_session, chapter, 1)
    ready_shot(db_session, chapter, 2)
    response = client.post(f'/api/novels/{novel.id}/chapters/{chapter.id}/grid/batch',
                           json={'step': 'board_generate'})
    assert response.status_code == 200, response.text
    batch_id = response.json()['data']['taskId']
    children = db_session.query(Task).filter(Task.parent_task_id == batch_id).order_by(Task.batch_order).all()
    assert [item.batch_order for item in children] == [1, 2]
    assert all(db_session.query(BackgroundJob).filter(BackgroundJob.task_id == item.id).count() == 1
               for item in children)

    async def fail_board(self, novel, chapter, shot, *, task=None):
        raise GridPipelineError('模拟首张整板失败')
    monkeypatch.setattr(GridPipeline, 'generate_board', fail_board)
    with pytest.raises(GridPipelineError):
        asyncio.run(run_grid_job(children[0].id))
    db_session.expire_all()
    assert db_session.get(Task, children[0].id).status == 'failed'
    assert db_session.get(Task, children[1].id).status == 'cancelled'
    assert db_session.get(Task, batch_id).status == 'failed'
    assert '第 1 项' in db_session.get(Task, batch_id).current_step
    retry = TaskService(db_session).retry_task(children[0].id)
    assert retry['success'] is True
    resumed = db_session.get(Task, retry['data']['taskId'])
    assert resumed.status == 'pending'
    assert resumed.source_task_id == children[0].id
    assert resumed.shot_id == children[0].shot_id
    assert db_session.query(BackgroundJob).filter(BackgroundJob.task_id == resumed.id).count() == 1


def test_grid_batch_prepares_missing_board_prompts_and_exposes_progress_fields(client, db_session, db_engine, monkeypatch):
    hold_grid_worker(monkeypatch, db_engine)
    novel, chapter = grid_novel_with_chapter(db_session)
    first = ready_shot(db_session, chapter, 1)
    second = ready_shot(db_session, chapter, 2)
    for shot in (first, second):
        grid = load_grid_data(shot.grid_data)
        grid.board_prompt = None
        shot.grid_data = dump_grid_data(grid)
    db_session.commit()
    response = client.post(f'/api/novels/{novel.id}/chapters/{chapter.id}/grid/batch',
                           json={'step': 'board_prepare'})
    assert response.status_code == 200, response.text
    parent_id = response.json()['data']['taskId']
    children = db_session.query(Task).filter(Task.parent_task_id == parent_id).order_by(Task.batch_order).all()
    assert len(children) == 2
    summary = client.get(f'/api/tasks/?chapter_id={chapter.id}&summary=true').json()['data']
    assert next(item for item in summary if item['id'] == parent_id)['gridStep'] == 'board_prepare'
    child_summary = next(item for item in summary if item['id'] == children[0].id)
    assert child_summary['shotId'] == first.id
    assert child_summary['batchOrder'] == 1
    detail = client.get(f'/api/tasks/{children[0].id}').json()['data']
    assert detail['metadata']['grid_step'] == 'board_prepare'


def test_submitted_grid_board_resumes_saved_receipt_without_resubmitting(db_session, tmp_path, monkeypatch):
    from app.models.workflow import Workflow

    novel, chapter = grid_novel_with_chapter(db_session)
    shot = ready_shot(db_session, chapter, 1)
    workflow = Workflow(name='image', type='shot', is_active=True,
                        workflow_json='{}', node_mapping=json.dumps({'save_image_node_id': 'save'}))
    db_session.add(workflow)
    db_session.flush()
    task = Task(type='grid_board_image', status='running', novel_id=novel.id, chapter_id=chapter.id,
                shot_id=shot.id, workflow_id=workflow.id, name='恢复整板', comfyui_prompt_id='already-submitted',
                workflow_json=json.dumps({'save': {'class_type': 'SaveImage', 'inputs': {}}}),
                metadata_json=json.dumps({'image_attempt': {'save_image_node_id': 'save'}}))
    db_session.add(task)
    db_session.commit()

    picture = io.BytesIO()
    Image.new('RGB', (1536, 864), 'red').save(picture, format='PNG')
    class FakeClient:
        async def wait_for_result(self, prompt_id, graph, node_id, **kwargs):
            assert prompt_id == 'already-submitted' and node_id == 'save'
            return {'success': True, 'image_url': 'http://comfy/saved.png'}
    class FakeBuilder:
        def build_shot_workflow(self, *args, **kwargs):
            raise AssertionError('submitted task must not build or submit a second graph')
    class FakeComfy:
        def __init__(self):
            self.client, self.builder = FakeClient(), FakeBuilder()
    class FakeResponse:
        content = picture.getvalue()
        def raise_for_status(self): pass
    class FakeHttp:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url): return FakeResponse()
    monkeypatch.setattr('app.services.grid_pipeline.ComfyUIService', FakeComfy)
    monkeypatch.setattr('app.services.grid_pipeline.httpx.AsyncClient', FakeHttp)
    monkeypatch.setattr(file_storage, 'base_dir', tmp_path)
    asyncio.run(GridPipeline(db_session).generate_board(novel, chapter, shot, task=task))
    assert db_session.get(Task, task.id).status == 'completed'
    assert load_grid_data(shot.grid_data).board_image_task_id == task.id


def test_cancel_during_grid_plan_does_not_cancel_serial_worker(db_session, db_engine, monkeypatch):
    hold_grid_worker(monkeypatch, db_engine)
    novel, chapter = grid_novel_with_chapter(db_session)
    task = enqueue_grid_job(db_session, novel, chapter, None, 'chapter_plan')

    async def cancel_while_waiting(self, novel, chapter, shot, kind, payload, **kwargs):
        with Session(db_engine) as other:
            running = other.get(Task, task.id)
            running.status = 'cancelled'
            other.commit()
        return {'shots': [{'description': '抵达村口', 'duration': 8,
                           'characters': [], 'scene': '', 'props': [], 'dialogues': []}]}, 'template'

    monkeypatch.setattr(GridPipeline, '_ask', cancel_while_waiting)
    asyncio.run(run_grid_job(task.id))
    db_session.expire_all()
    assert db_session.get(Task, task.id).status == 'cancelled'
    assert db_session.query(Shot).filter(Shot.chapter_id == chapter.id).count() == 0


def test_reconcile_completed_children_after_restart(db_session, db_engine, monkeypatch):
    hold_grid_worker(monkeypatch, db_engine)
    novel, chapter = grid_novel_with_chapter(db_session)
    batch = Task(type='grid_batch', status='running', novel_id=novel.id,
                 chapter_id=chapter.id, name='批量宫格', progress=0,
                 metadata_json=json.dumps({'expected_count': 1}))
    db_session.add(batch)
    db_session.flush()
    child = Task(type='grid_board_image', status='completed', novel_id=novel.id,
                 chapter_id=chapter.id, parent_task_id=batch.id, batch_order=1,
                 name='整板', progress=100)
    db_session.add(child)
    db_session.commit()
    assert reconcile_grid_batches() == 1
    db_session.expire_all()
    assert db_session.get(Task, batch.id).status == 'completed'
    assert db_session.get(Task, batch.id).progress == 100
