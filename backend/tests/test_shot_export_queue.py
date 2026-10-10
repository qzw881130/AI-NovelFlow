import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.models.background_job import BackgroundJob
from app.services import shot_export_service as exports
from app.services import continuous_clip_av as av
from app.services.background_workers import WorkerManager


@pytest.fixture
def scope(db_session, db_engine, monkeypatch, tmp_path):
    novel = Novel(title='export')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='chapter', content='text')
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, duration=10,
                video_director_plan=json.dumps({'canonical_visual_plan': True, 'clip_plan_revision': 1, 'clip_plan': []}))
    db_session.add(shot)
    db_session.commit()
    sessions = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    manager = WorkerManager(sessions)
    signalled = []
    # Persist normally but leave execution under explicit test control.
    monkeypatch.setattr(manager, 'worker', lambda name: SimpleNamespace(enqueue=lambda request: signalled.append(manager.persist(request, name)), signal=signalled.append))
    monkeypatch.setattr(exports, 'worker_manager', manager)
    monkeypatch.setattr(exports, 'SessionLocal', sessions)
    monkeypatch.setattr(exports.file_storage, 'base_dir', tmp_path)
    base = f'/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}'
    return SimpleNamespace(novel=novel, chapter=chapter, shot=shot, base=base, manager=manager, signalled=signalled, sessions=sessions)


def test_submit_returns_queued_receipt_and_deduplicates_without_building(client, scope, monkeypatch):
    from app.api import shots
    monkeypatch.setattr(shots, 'write_shot_video_materials_package', lambda *args: pytest.fail('HTTP must not build'))
    response = client.post(f'{scope.base}/export-video-materials?include=plan')
    assert response.status_code == 202
    data = response.json()['data']
    assert data['status'] == 'pending'
    assert client.post(f'{scope.base}/export-video-materials?include=plan').json()['data']['task_id'] == data['task_id']
    assert len(scope.signalled) == 1
    assert client.get(f'{scope.base}/exports/{data["task_id"]}/download').status_code == 409
    assert client.post(f'{scope.base}/export-video-materials?include=invalid').status_code == 400
    assert client.get(f'{scope.base}/exports/missing').status_code == 404
    assert client.get(f'{scope.base.replace(scope.shot.id, "other")}/exports/{data["task_id"]}').status_code == 404


@pytest.mark.asyncio
async def test_disk_export_survives_worker_restart_and_streams_selected_zip(client, scope, db_session):
    data = client.post(f'{scope.base}/export-video-materials?include=plan').json()['data']
    job = db_session.query(BackgroundJob).filter_by(task_id=data['task_id']).one()
    job.status = 'running'
    db_session.commit()
    assert scope.manager.resume_persisted() == 1
    await scope.manager.run_persisted(job.id)
    status = client.get(f'{scope.base}/exports/{data["task_id"]}').json()['data']
    assert status['status'] == 'completed'
    assert status['progress'] == 100
    response = client.get(status['download_url'])
    assert response.status_code == 200
    task = db_session.query(Task).filter_by(id=data['task_id']).one()
    db_session.refresh(task)
    with ZipFile(exports.export_file(task)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['selected_sections'] == ['plan']
        assert all(not name.endswith('.mp4') for name in archive.namelist())
    assert not list(exports.export_file(task).parent.glob('*.part'))
    exports.export_file(task).unlink()
    assert client.get(status['download_url']).status_code == 410


@pytest.mark.asyncio
async def test_slow_builder_does_not_block_event_loop_or_status_and_cancel_cannot_publish(client, scope, monkeypatch, db_session):
    from app.api import shots
    entered, release = threading.Event(), threading.Event()
    def slow(_db, _novel, _chapter, _shot, _selected, path, progress):
        entered.set()
        assert release.wait(5)
        Path(path).write_bytes(b'zip')
        return 'test.zip'
    monkeypatch.setattr(shots, 'write_shot_video_materials_package', slow)
    data = client.post(f'{scope.base}/export-video-materials?include=plan').json()['data']
    runner = asyncio.create_task(exports.run_export_task(data['task_id']))
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait), 2)
        # This coroutine and HTTP status can run while the builder is blocked.
        await asyncio.wait_for(asyncio.sleep(0), .2)
        status = client.get(f'{scope.base}/exports/{data["task_id"]}').json()['data']
        assert status['status'] == 'running'
        db_session.query(Task).filter_by(id=data['task_id']).update({'status': 'cancelled'})
        db_session.commit()
    finally:
        release.set()
        await runner
    task = db_session.query(Task).filter_by(id=data['task_id']).one()
    db_session.refresh(task)
    assert task.status == 'cancelled' and not task.result_url
    assert not exports.export_file(task).exists()
    assert not list(exports.export_file(task).parent.glob('*.part'))


def test_failure_records_error_and_removes_partial_zip(client, scope, monkeypatch, db_session):
    from app.api import shots
    def fail(*args):
        Path(args[5]).write_bytes(b'incomplete')
        raise ValueError('failed archive')
    monkeypatch.setattr(shots, 'write_shot_video_materials_package', fail)
    task_id = client.post(f'{scope.base}/export-video-materials?include=plan').json()['data']['task_id']
    with pytest.raises(ValueError, match='failed archive'):
        exports._build_export(task_id)
    task = db_session.query(Task).filter_by(id=task_id).one()
    db_session.refresh(task)
    assert task.status == 'failed' and task.error_message == 'failed archive'
    assert not exports.export_file(task).exists()
    assert not list(exports.export_file(task).parent.glob('*.part'))


def test_export_probe_cache_is_scoped_and_invalidated_by_changed_file(monkeypatch, tmp_path):
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'old')
    calls = []
    monkeypatch.setattr(av, '_probe_clip_av', lambda p: calls.append(p) or {'sha256': Path(p).read_bytes().hex()})
    @av.cache_export_av_probes
    def run():
        first = av.probe_clip_av(str(path))
        first['sha256'] = 'mutated return'
        assert av.probe_clip_av(str(path))['sha256'] == b'old'.hex()
        assert len(calls) == 1
        path.write_bytes(b'new-longer')
        assert av.probe_clip_av(str(path))['sha256'] == b'new-longer'.hex()
        assert len(calls) == 2
    run()
    av.probe_clip_av(str(path))
    av.probe_clip_av(str(path))
    assert len(calls) == 4  # ordinary generation/other exports do not reuse it


def test_export_uses_stored_mp4_count_with_hash_check_and_decodes_only_when_missing(monkeypatch, tmp_path):
    video = tmp_path / 'clip.mp4'
    video.write_bytes(b'media')
    calls = []
    stream = {'codec_type': 'video', 'avg_frame_rate': '24/1', 'r_frame_rate': '24/1',
              'nb_frames': '240', 'width': 960, 'height': 544}
    def probe(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'streams': [
            {**stream, **({'nb_read_frames': '240'} if '-count_frames' in command else {})}]}))
    monkeypatch.setattr(av.subprocess, 'run', probe)
    @av.cache_export_av_probes
    def export_probe():
        return av.probe_clip_av(str(video))
    result = export_probe()
    assert result['frame_count'] == 240 and result['sha256']
    assert len(calls) == 1 and '-count_frames' not in calls[0][0]
    calls.clear()
    stream.pop('nb_frames')
    assert export_probe()['frame_count'] == 240
    assert len(calls) == 2 and '-count_frames' in calls[1][0]
    assert calls[1][1]['timeout'] == 600
    calls.clear()
    av.probe_clip_av(str(video))
    assert '-count_frames' in calls[0][0] and calls[0][1]['timeout'] == 60


def test_export_retry_creates_durable_new_attempt_and_keeps_failure_history(client, scope, db_session):
    task_id = client.post(f'{scope.base}/export-video-materials?include=plan').json()['data']['task_id']
    original = db_session.query(Task).filter_by(id=task_id).one()
    original.status = 'failed'
    original.error_message = 'previous timeout'
    db_session.commit()
    response = client.post(f'/api/tasks/{task_id}/retry')
    assert response.status_code == 200
    retry_id = response.json()['data']['taskId']
    assert retry_id != task_id
    retry = db_session.query(Task).filter_by(id=retry_id).one()
    assert retry.type == 'shot_export' and retry.source_task_id == task_id
    assert json.loads(retry.metadata_json)['sections'] == ['plan']
    original = db_session.query(Task).filter_by(id=task_id).one()
    assert original.status == 'failed' and original.error_message == 'previous timeout'
    assert db_session.query(BackgroundJob).filter_by(task_id=retry_id, status='queued').count() == 1
