"""A2-R1 mutation boundaries: isolated SQLite, local files, mocked generation."""
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api import shots as api
from app.models.shot import Shot
from app.models.task import Task
from app.repositories import NovelRepository, ChapterRepository, ShotRepository, TaskRepository, PromptTemplateRepository
from app.schemas.shot import GenerateShotImageRequest, ShotImageReplaceRequest
from app.services.canonical_execution_invalidation import CanonicalExecutionConflict
from app.services.required_visual_state_images import commit_visual_state_image, state_provenance, project_required_execution_images
from app.services import shot_image_service as images
from app.services.task_service import TaskService
from test_required_visual_state_preparation import fixture, plan, save, task


def repos(db):
    return NovelRepository(db), ChapterRepository(db), TaskRepository(db), ShotRepository(db)


async def submit_start(db, shot, monkeypatch):
    monkeypatch.setattr(api, '_build_shot_image_reference_readiness', lambda *a: {'available_reference_count': 1, 'manifest': []})
    monkeypatch.setattr(api, '_resolve_shot_image_workflow_type', lambda *a: 'shot')
    monkeypatch.setattr(api.TaskService, 'validate_workflow_node_mapping', lambda *a: (True, None))
    monkeypatch.setattr(api, '_resolve_shot_image_prompt_text', AsyncMock(return_value=('mock prompt', 'mock template')))
    enqueue = MagicMock(); delete = MagicMock()
    monkeypatch.setattr(api, 'generate_shot_task', enqueue)
    monkeypatch.setattr(api.file_storage, 'delete_shot_image', delete)
    novel, chapter, tasks, shots = repos(db)
    result = await api._prepare_and_enqueue_shot_image_generation(
        'novel', 'chapter', shot.id, GenerateShotImageRequest(), db, novel, chapter, tasks,
        SimpleNamespace(get_active_by_type=lambda _: SimpleNamespace(id='mock-workflow', name='mock')),
        shots, PromptTemplateRepository(db), SimpleNamespace())
    return db.get(Task, result['data']['taskId']), enqueue, delete


@pytest.mark.asyncio
async def test_ordinary_canonical_start_freezes_provenance(db_session, fixture, monkeypatch):
    expected = state_provenance(fixture, 1)
    row, enqueue, delete = await submit_start(db_session, fixture, monkeypatch)
    assert json.loads(row.metadata_json)['canonical_image_provenance'] == expected
    assert fixture.image_task_id == row.id
    assert json.loads(row.metadata_json)['canonical_image_previous_url']
    delete.assert_not_called(); enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_noncanonical_ordinary_generation_keeps_legacy_behavior(db_session, fixture, monkeypatch):
    p = plan(fixture); p.pop('canonical_visual_plan'); save(db_session, fixture, p)
    row, enqueue, delete = await submit_start(db_session, fixture, monkeypatch)
    assert not json.loads(row.metadata_json or '{}').get('canonical_image_provenance')
    delete.assert_called_once(); enqueue.assert_called_once()
    images._update_shot_image(db_session, 'chapter', 1, None, '/legacy.png', task_id=row.id)
    assert fixture.image_url == '/legacy.png'


@pytest.mark.parametrize('change', ['revision', 'state', 'fingerprint', 'attempt', 'missing_provenance'])
@pytest.mark.asyncio
async def test_stale_start_completion_rejected_before_download(db_session, fixture, monkeypatch, change):
    row = task(db_session, fixture, 1)
    p = plan(fixture)
    if change == 'revision': p['clip_plan_revision'] += 1
    if change == 'state': p['keyframes'][0]['role'] = 'INTERMEDIATE'
    if change == 'fingerprint': p['keyframes'][0]['description'] = 'changed'
    if change == 'attempt': fixture.image_task_id = 'new-attempt'
    if change == 'missing_provenance': row.metadata_json = '{}'
    save(db_session, fixture, p)
    before = (fixture.image_url, fixture.image_status, fixture.image_task_id, fixture.video_director_plan)
    download = AsyncMock(return_value='/should-not-download.png')
    monkeypatch.setattr(images.file_storage, 'download_image', download)
    with pytest.raises(CanonicalExecutionConflict):
        await images._save_generated_image({'image_url': 'mock-output'}, row, None, 'novel', 'chapter', 1,
                                          db_session, row.id, fixture.id, ShotRepository(db_session))
    download.assert_not_awaited()
    images._fail_shot_image_task(db_session, row, 'CANONICAL_IMAGE_STATE_CHANGED', 'rejected', 'chapter', 1)
    assert row.status == 'failed'
    assert (fixture.image_url, fixture.image_status, fixture.image_task_id, fixture.video_director_plan) == before


def consumer(db, shot, *, active=False, direct=True, clip_index=1):
    p = plan(shot)
    row = Task(id=f'consumer-{clip_index}', type='shot_video', shot_id=shot.id, name='consumer',
               status='running' if active else 'completed', result_url='/clip.mp4',
               metadata_json=json.dumps({'execution_scope': 'CLIP', 'clip_index': clip_index,
                 'clip_plan_revision': p['clip_plan_revision'], 'execution_contract': {'artifact_kind': 'CLIP_ONLY'},
                 'video_reference_manifest': {'references': [{'source_keyframe_index': 1, 'image_url': shot.image_url}] if direct else []}}))
    p['clip_plan'][clip_index-1].update(generated_by_task_id=row.id, video_url=row.result_url, execution_status='APPROVED')
    db.add(row); save(db, shot, p)
    return row


async def replace(db, shot, new_file, monkeypatch):
    monkeypatch.setattr(api, 'url_to_local_path', lambda url: str(new_file) if url == '/new.png' else None)
    return await api.replace_shot_image('novel', 'chapter', shot.id, ShotImageReplaceRequest(image_url='/new.png'),
                                       ChapterRepository(db), ShotRepository(db))


@pytest.mark.parametrize('kind', ['replace', 'upload'])
@pytest.mark.asyncio
async def test_manual_start_supersedes_attempt_and_old_result(db_session, fixture, tmp_path, monkeypatch, kind):
    row = task(db_session, fixture, 1)
    old = Path(fixture.image_url); fixture.image_path = str(old); db_session.commit()
    new = tmp_path/'replacement.png'; new.write_bytes(b'manual')
    if kind == 'replace':
        await replace(db_session, fixture, new, monkeypatch)
    else:
        monkeypatch.setattr(api.file_storage, 'base_dir', tmp_path)
        monkeypatch.setattr(api.file_storage, 'get_shot_image_path', lambda **kw: tmp_path/'upload.png')
        await api.upload_shot_image('novel', 'chapter', fixture.id,
            UploadFile(io.BytesIO(b'manual'), filename='upload.png', headers=Headers({'content-type': 'image/png'})),
            db_session, ChapterRepository(db_session), ShotRepository(db_session))
    binding = (fixture.image_url, fixture.image_status, fixture.image_task_id, fixture.video_director_plan)
    assert fixture.image_task_id is None and fixture.image_status == 'completed'
    with pytest.raises(CanonicalExecutionConflict):
        images._update_shot_image(db_session, 'chapter', 1, None, '/old-task.png', task_id=row.id)
    images._fail_shot_image_task(db_session, row, 'CANONICAL_IMAGE_ATTEMPT_CHANGED', 'rejected', 'chapter', 1)
    assert (fixture.image_url, fixture.image_status, fixture.image_task_id, fixture.video_director_plan) == binding
    assert not old.exists() and new.read_bytes() == b'manual'


@pytest.mark.parametrize('kind', ['replace', 'upload'])
@pytest.mark.parametrize('conflict', ['physical', 'closure'])
@pytest.mark.asyncio
async def test_active_consumer_conflict_preserves_binding_and_old_file(db_session, fixture, tmp_path, monkeypatch, kind, conflict):
    if conflict == 'physical': consumer(db_session, fixture, active=True)
    else:
        consumer(db_session, fixture)
        consumer(db_session, fixture, active=True, direct=False, clip_index=2)
    old = Path(fixture.image_url); fixture.image_path = str(old); db_session.commit()
    before = (fixture.image_url, fixture.image_task_id, fixture.video_director_plan)
    new = tmp_path/'new.png'; new.write_bytes(b'new')
    delete = MagicMock(); monkeypatch.setattr(api.file_storage, 'delete_shot_image', delete)
    with pytest.raises(HTTPException) as exc:
        if kind == 'replace': await replace(db_session, fixture, new, monkeypatch)
        else:
            monkeypatch.setattr(api.file_storage, 'base_dir', tmp_path)
            # Same-second legacy name collision must never overwrite old bytes.
            monkeypatch.setattr(api.file_storage, 'get_shot_image_path', lambda **kw: old)
            await api.upload_shot_image('novel', 'chapter', fixture.id,
                UploadFile(io.BytesIO(b'new'), filename='x.png', headers=Headers({'content-type': 'image/png'})),
                db_session, ChapterRepository(db_session), ShotRepository(db_session))
    assert exc.value.status_code == 409
    db_session.refresh(fixture)
    assert (fixture.image_url, fixture.image_task_id, fixture.video_director_plan) == before
    assert old.read_bytes() == b'image'; delete.assert_not_called()


@pytest.mark.asyncio
async def test_replacement_invalidates_actual_consumers_and_closure_only(db_session, fixture, tmp_path, monkeypatch):
    consumer(db_session, fixture)
    p = plan(fixture)
    for c in p['clip_plan'][1:]: c.update(video_url=f"/c{c['clip_index']}.mp4", execution_status='APPROVED')
    p['clip_plan'][3].update(capability='GENERATE', previous_clip_index=None)
    p['merged_video_url'] = '/assembled.mp4'; save(db_session, fixture, p)
    before = plan(fixture)
    new = tmp_path/'new.png'; new.write_bytes(b'image')
    await replace(db_session, fixture, new, monkeypatch)
    after = plan(fixture)
    assert [c['execution_status'] for c in after['clip_plan']] == ['PLANNED', 'PLANNED', 'PLANNED', 'APPROVED', 'APPROVED', 'APPROVED']
    assert 'merged_video_url' not in after
    assert after['clip_plan'][3:] == before['clip_plan'][3:]
    assert after['clip_plan_revision'] == before['clip_plan_revision']
    assert [(c['capability'], c['selected_temporal_target_ids']) for c in after['clip_plan']] == [(c['capability'], c['selected_temporal_target_ids']) for c in before['clip_plan']]


@pytest.mark.parametrize('index', [4, '4'])
@pytest.mark.parametrize('attempt', ['legacy-task', None])
def test_noncanonical_plan_keyframe_index_sync(db_session, fixture, index, attempt):
    p = plan(fixture); p.pop('canonical_visual_plan'); p['keyframes'][3]['image_url'] = '/old.png'; save(db_session, fixture, p)
    p['keyframes'][3].update(index=index, image_task_id='old-task'); save(db_session, fixture, p)
    frames = json.loads(fixture.keyframes); frames[2]['plan_keyframe_index'] = index; fixture.keyframes = json.dumps(frames); db_session.commit()
    commit_visual_state_image(db_session, fixture, '/new.png', frame_index=2, expected_provenance=None, task_id=attempt)
    db_session.commit()
    assert json.loads(fixture.keyframes)[2]['image_url'] == '/new.png'
    assert plan(fixture)['keyframes'][3]['image_url'] == '/new.png'
    assert plan(fixture)['keyframes'][3]['image_task_id'] == (attempt or 'old-task')


async def video_submit(db, shot, *, batch=False, clip=1):
    novel, chapter, tasks, shots = repos(db)
    if batch:
        return await api.generate_shot_videos_batch('novel', 'chapter', api.BatchShotVideoRequest(shot_ids=[shot.id]), db, novel, chapter, shots)
    return await api.execute_semantic_clip('novel', 'chapter', shot.id, clip, api.SemanticClipGenerateRequest(clip_plan_revision=2), db, novel, chapter, tasks, shots)


@pytest.mark.parametrize('batch', [False, True])
@pytest.mark.parametrize('url', [None, '/api/files/dead.png'])
@pytest.mark.asyncio
async def test_video_physical_missing_before_any_task(db_session, fixture, batch, url):
    p = plan(fixture); p['clip_plan'] = p['clip_plan'][:1]; fixture.image_url = url; save(db_session, fixture, p)
    assert not project_required_execution_images(fixture, p)[0]['ready']
    if url:
        # Reproduce the review discrepancy: URL-only execution readiness passes.
        assert api.get_canonical_execution_readiness(fixture, p)['ready']
    with pytest.raises(HTTPException) as exc: await video_submit(db_session, fixture, batch=batch)
    assert exc.value.status_code == 409
    if url: assert exc.value.detail['code'] == 'REQUIRED_IMAGES_MISSING'
    assert db_session.query(Task).count() == 0


@pytest.mark.parametrize('batch', [False, True])
@pytest.mark.asyncio
async def test_physical_ready_and_unselected_missing_pass_image_gate(db_session, fixture, monkeypatch, batch):
    p = plan(fixture); p['clip_plan'] = p['clip_plan'][:1]; p['keyframes'][1]['image_url'] = '/dead-unselected.png'; save(db_session, fixture, p)
    p['clip_plan'][0]['planned_duration'] = 8.05; fixture.duration = 68; save(db_session, fixture, p)
    assert all(i['ready'] for i in project_required_execution_images(fixture, p))
    if batch:
        enqueue = MagicMock(); monkeypatch.setattr(api, 'enqueue_shot_video_batch_task', enqueue)
        result = await video_submit(db_session, fixture, batch=True)
        assert result['success']; enqueue.assert_called_once()
    else:
        # A later workflow guard proves the physical image gate passed without generating.
        with pytest.raises(HTTPException) as exc: await video_submit(db_session, fixture)
        assert exc.value.status_code == 400 and '工作流' in str(exc.value.detail)
        assert db_session.query(Task).count() == 0


@pytest.mark.parametrize('batch', [False, True])
@pytest.mark.asyncio
async def test_selected_temporal_dead_file_blocks_before_previous_av_and_tasks(db_session, fixture, monkeypatch, batch):
    p = plan(fixture); p['clip_plan'] = p['clip_plan'][:3]
    p['temporal_anchors'][0]['image_url'] = '/api/files/dead-kf4.png'; save(db_session, fixture, p)
    previous = MagicMock(side_effect=AssertionError('must block before Previous AV'))
    monkeypatch.setattr(api, 'resolve_extend_previous_av', previous)
    with pytest.raises(HTTPException) as exc: await video_submit(db_session, fixture, batch=batch, clip=3)
    assert exc.value.status_code == 409
    assert db_session.query(Task).count() == 0; previous.assert_not_called()


@pytest.mark.parametrize('change', ['revision', 'fingerprint', 'attempt', 'missing_provenance'])
@pytest.mark.asyncio
async def test_full_reconcile_stale_start_terminal_and_no_unrelated_mutation(db_session, fixture, monkeypatch, change):
    row = task(db_session, fixture, 1)
    row.comfyui_prompt_id = 'mock-completed'
    row.updated_at = datetime.utcnow() - timedelta(minutes=2)
    p = plan(fixture)
    if change == 'revision': p['clip_plan_revision'] += 1
    if change == 'fingerprint': p['keyframes'][0]['description'] = 'new state'
    if change == 'missing_provenance': row.metadata_json = '{}'
    current = task(db_session, fixture, 1, id='new-attempt', status='pending')
    fixture.image_url = '/current-new.png'; fixture.image_status = 'generating'; save(db_session, fixture, p)
    untouched = Shot(id='unrelated', chapter_id='chapter', index=2, image_url='/unrelated.png', image_status='completed')
    db_session.add(untouched); db_session.commit()
    row.updated_at = datetime.utcnow() - timedelta(minutes=2); db_session.commit()
    before = (fixture.image_url, fixture.image_status, fixture.image_task_id, fixture.keyframes, fixture.video_director_plan)
    service = TaskService(db_session)
    service.comfyui_service.get_queue_info = AsyncMock(return_value={})
    service.comfyui_service.client.get_prompt_state = AsyncMock(return_value={'state': 'completed', 'history': {'outputs': {'1': {'images': [{'filename': 'old.png'}]}}}})
    service.comfyui_service.client._parse_outputs = MagicMock(return_value={'image_url': 'mock-old-output'})
    download = AsyncMock(return_value='/old-output.png'); monkeypatch.setattr('app.services.task_service.file_storage.download_image', download)
    assert await service.reconcile_active_tasks([row], db_session) == 1
    db_session.refresh(row); db_session.refresh(fixture); db_session.refresh(current); db_session.refresh(untouched)
    assert row.status == 'failed' and row.completed_at and 'CANONICAL_IMAGE_' in row.error_message
    assert (fixture.image_url, fixture.image_status, fixture.image_task_id, fixture.keyframes, fixture.video_director_plan) == before
    assert current.status == 'pending' and untouched.image_url == '/unrelated.png' and untouched.image_status == 'completed'
    assert db_session.query(Task).count() == 2
    assert db_session.query(Task).filter(Task.type.like('%video%')).count() == 0
    download.assert_not_awaited(); service.comfyui_service.client._parse_outputs.assert_not_called()


@pytest.mark.parametrize('kind', ['replace', 'upload'])
@pytest.mark.asyncio
async def test_old_file_cleanup_only_after_committed_binding(db_session, fixture, tmp_path, monkeypatch, kind):
    from sqlalchemy.orm import Session
    old = Path(fixture.image_url); fixture.image_path = str(old)
    p = plan(fixture); p['keyframes'][0].update(image_url=str(old), image_task_id='old-state-task'); save(db_session, fixture, p)
    cleanup = api._cleanup_replaced_main_image
    observed = []
    def checked_cleanup(previous, new):
        assert old.read_bytes() == b'image'
        with Session(db_session.bind) as independent:
            persisted = independent.get(Shot, fixture.id)
            assert persisted.image_path == str(new) and persisted.image_task_id is None
            assert persisted.image_status == 'completed'
        observed.append(True); cleanup(previous, new)
    monkeypatch.setattr(api, '_cleanup_replaced_main_image', checked_cleanup)
    new = tmp_path/'replacement.png'; new.write_bytes(b'manual')
    if kind == 'replace':
        await replace(db_session, fixture, new, monkeypatch)
    else:
        monkeypatch.setattr(api.file_storage, 'base_dir', tmp_path)
        # Exercise a path that would collide with the old file in legacy upload.
        monkeypatch.setattr(api.file_storage, 'get_shot_image_path', lambda **kw: old)
        await api.upload_shot_image('novel', 'chapter', fixture.id,
            UploadFile(io.BytesIO(b'manual'), filename='x.png', headers=Headers({'content-type': 'image/png'})),
            db_session, ChapterRepository(db_session), ShotRepository(db_session))
    monkeypatch.setattr('app.services.required_visual_state_images.url_to_local_path', lambda url: fixture.image_path)
    assert observed == [True] and not old.exists()
    assert project_required_execution_images(fixture, plan(fixture), clip_indexes=[1])[0]['ready']
    assert plan(fixture)['keyframes'][0]['image_task_id'] is None


@pytest.mark.parametrize('kind', ['replace', 'upload'])
@pytest.mark.asyncio
async def test_db_commit_failure_keeps_old_file_and_binding(db_session, fixture, tmp_path, monkeypatch, kind):
    old = Path(fixture.image_url); fixture.image_path = str(old); db_session.commit()
    before = (fixture.image_url, fixture.image_path, fixture.image_task_id, fixture.video_director_plan)
    new = tmp_path/'new.png'; new.write_bytes(b'new')
    monkeypatch.setattr(db_session, 'commit', MagicMock(side_effect=RuntimeError('mock commit failure')))
    if kind == 'replace':
        with pytest.raises(RuntimeError, match='mock commit failure'):
            await replace(db_session, fixture, new, monkeypatch)
    else:
        monkeypatch.setattr(api.file_storage, 'base_dir', tmp_path)
        monkeypatch.setattr(api.file_storage, 'get_shot_image_path', lambda **kw: old)
        with pytest.raises(HTTPException) as exc:
            await api.upload_shot_image('novel', 'chapter', fixture.id,
                UploadFile(io.BytesIO(b'new'), filename='x.png', headers=Headers({'content-type': 'image/png'})),
                db_session, ChapterRepository(db_session), ShotRepository(db_session))
        assert exc.value.status_code == 500
        assert not list(tmp_path.glob('main_*.png'))
    db_session.rollback(); db_session.refresh(fixture)
    assert (fixture.image_url, fixture.image_path, fixture.image_task_id, fixture.video_director_plan) == before
    assert old.read_bytes() == b'image' and new.read_bytes() == b'new'


@pytest.mark.asyncio
async def test_manual_replacement_during_start_prepare_retains_source_for_invalidation(db_session, fixture, tmp_path, monkeypatch):
    old = Path(fixture.image_url); fixture.image_path = str(old); db_session.commit()
    consumer(db_session, fixture)
    row, _, _ = await submit_start(db_session, fixture, monkeypatch)
    assert fixture.image_url is None
    new = tmp_path/'new.png'; new.write_bytes(b'manual')
    # Resolve the frozen URL after START generation cleared the Shot path.
    monkeypatch.setattr(api, 'url_to_local_path', lambda url: str(old) if url == str(old) else str(new))
    await api.replace_shot_image('novel', 'chapter', fixture.id, ShotImageReplaceRequest(image_url='/new.png'),
                                 ChapterRepository(db_session), ShotRepository(db_session))
    assert fixture.image_task_id is None and fixture.image_url == '/new.png'
    assert plan(fixture)['clip_plan'][0]['execution_status'] == 'PLANNED'
    assert not old.exists()
    with pytest.raises(CanonicalExecutionConflict):
        images._update_shot_image(db_session, 'chapter', 1, None, '/old-output.png', task_id=row.id)


@pytest.mark.asyncio
async def test_full_reconcile_stale_keyframe_terminal(db_session, fixture, monkeypatch):
    row = task(db_session, fixture, 4)
    row.comfyui_prompt_id = 'mock-completed'
    p = plan(fixture); p['clip_plan_revision'] += 1; p['keyframes'][3]['description'] = 'new state'; save(db_session, fixture, p)
    current = task(db_session, fixture, 4, id='new-kf4-attempt', status='pending')
    frames = json.loads(fixture.keyframes); frames[2]['image_url'] = '/new-kf4.png'; fixture.keyframes = json.dumps(frames)
    p = plan(fixture); p['keyframes'][3].update(image_url='/new-kf4.png', image_task_id=current.id); save(db_session, fixture, p)
    row.updated_at = datetime.utcnow() - timedelta(minutes=2); db_session.commit()
    before = (fixture.image_url, fixture.keyframes, fixture.video_director_plan)
    service = TaskService(db_session)
    service.comfyui_service.get_queue_info = AsyncMock(return_value={})
    service.comfyui_service.client.get_prompt_state = AsyncMock(return_value={'state': 'completed', 'history': {'outputs': {'1': {'images': [{'filename': 'old.png'}]}}}})
    download = AsyncMock(); monkeypatch.setattr('app.services.task_service.file_storage.download_image', download)
    assert await service.reconcile_active_tasks([row], db_session) == 1
    assert row.status == 'failed' and row.completed_at and 'CANONICAL_IMAGE_STATE_CHANGED' in row.error_message
    assert (fixture.image_url, fixture.keyframes, fixture.video_director_plan) == before
    assert json.loads(fixture.keyframes)[2]['image_task_id'] == current.id and current.status == 'pending'
    assert db_session.query(Task).count() == 2
    download.assert_not_awaited()


@pytest.mark.parametrize('change', ['revision', 'manual_replacement', 'missing_provenance'])
@pytest.mark.asyncio
async def test_actual_image_worker_stale_task_is_terminal(db_session, fixture, tmp_path, monkeypatch, change):
    row = task(db_session, fixture, 1)
    p = plan(fixture)
    if change == 'revision': p['clip_plan_revision'] += 1
    if change == 'missing_provenance': row.metadata_json = '{}'
    save(db_session, fixture, p)
    if change == 'manual_replacement':
        new = tmp_path/'new.png'; new.write_bytes(b'manual')
        await replace(db_session, fixture, new, monkeypatch)
    before = (fixture.image_url, fixture.image_status, fixture.image_task_id, fixture.video_director_plan)
    monkeypatch.setattr(images, 'SessionLocal', lambda: db_session)
    monkeypatch.setattr(db_session, 'close', MagicMock())
    comfy = MagicMock(side_effect=AssertionError('stale task must fail before ComfyUI'))
    monkeypatch.setattr(images, 'ComfyUIService', comfy)
    await images.generate_shot_image_task(row.id, 'novel', 'chapter', 1, 'mock prompt', 'mock-workflow')
    assert row.status == 'failed' and row.completed_at and 'CANONICAL_IMAGE_' in row.error_message
    assert (fixture.image_url, fixture.image_status, fixture.image_task_id, fixture.video_director_plan) == before
    assert db_session.query(Task).count() == 1; comfy.assert_not_called()


@pytest.mark.asyncio
async def test_canonical_normal_completion_commits_current_attempt(db_session, fixture, tmp_path, monkeypatch):
    row = task(db_session, fixture, 1)
    new = tmp_path/'new.png'; new.write_bytes(b'generated')
    monkeypatch.setattr(images.file_storage, 'base_dir', tmp_path)
    download = AsyncMock(return_value=str(new)); monkeypatch.setattr(images.file_storage, 'download_image', download)
    await images._save_generated_image({'image_url': 'mock-output'}, row, None, 'novel', 'chapter', 1,
                                      db_session, row.id, fixture.id, ShotRepository(db_session))
    assert row.status == 'completed' and row.result_url == fixture.image_url == '/api/files/new.png'
    assert fixture.image_task_id == row.id and fixture.image_path == str(new)
    assert row.id in download.await_args.kwargs['character_name']


@pytest.mark.asyncio
async def test_ordinary_start_replan_during_prompt_rejected_before_task(db_session, fixture, monkeypatch):
    novel, chapter, tasks, shots = repos(db_session)
    monkeypatch.setattr(api, '_build_shot_image_reference_readiness', lambda *a: {'available_reference_count': 1, 'manifest': []})
    monkeypatch.setattr(api.TaskService, 'validate_workflow_node_mapping', lambda *a: (True, None))
    async def replan(*args):
        p = plan(fixture); p['clip_plan_revision'] += 1; save(db_session, fixture, p)
        return 'mock prompt', 'mock template'
    monkeypatch.setattr(api, '_resolve_shot_image_prompt_text', replan)
    enqueue = MagicMock(); monkeypatch.setattr(api, 'generate_shot_task', enqueue)
    old = fixture.image_url
    with pytest.raises(HTTPException) as exc:
        await api.generate_shot_image('novel', 'chapter', fixture.id, GenerateShotImageRequest(workflow_type='shot'),
            db_session, novel, chapter, tasks,
            SimpleNamespace(get_active_by_type=lambda _: SimpleNamespace(id='mock-workflow', name='mock')),
            shots, PromptTemplateRepository(db_session), SimpleNamespace())
    assert exc.value.status_code == 409 and 'CANONICAL_IMAGE_STATE_CHANGED' in exc.value.detail
    assert fixture.image_url == old and fixture.image_task_id is None
    assert db_session.query(Task).count() == 0; enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_batch_later_selected_shot_missing_leaves_zero_parent(db_session, fixture):
    p = plan(fixture); p['clip_plan'] = p['clip_plan'][:1]; save(db_session, fixture, p)
    other = Shot(id='second-shot', chapter_id='chapter', index=2, description='second',
                 image_url='/api/files/dead-second.png', video_director_plan=json.dumps(p), keyframes=fixture.keyframes)
    db_session.add(other); db_session.commit()
    novel, chapter, _, shots = repos(db_session)
    with pytest.raises(HTTPException) as exc:
        await api.generate_shot_videos_batch('novel', 'chapter',
            api.BatchShotVideoRequest(shot_ids=[fixture.id, other.id]), db_session, novel, chapter, shots)
    assert exc.value.status_code == 409 and exc.value.detail['shot_id'] == other.id
    assert db_session.query(Task).count() == 0
