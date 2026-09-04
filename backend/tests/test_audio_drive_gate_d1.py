import asyncio
import json
from datetime import datetime, timedelta

from app.models.audio_drive import ShotAudioEvent, AudioEventTTSAsset
from app.models.novel import Chapter, Character, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories.task import TaskRepository
from app.services.audio_drive_service import AudioDriveService


def _create_task(db_session, status="pending", heartbeat_at=None, claim_token=None, worker_id=None):
    task = Task(
        type="audio_event_tts",
        status=status,
        name="TTS",
        current_step="等待处理",
        metadata_json=json.dumps({"audio_event_id": "event-1"}),
        heartbeat_at=heartbeat_at,
        claim_token=claim_token,
        worker_id=worker_id,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


def _create_tts_fixture(db_session, tmp_path):
    novel = Novel(title="Gate D1")
    db_session.add(novel)
    db_session.commit()
    db_session.refresh(novel)

    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"ref")
    character = Character(novel_id=novel.id, name="A", reference_audio_url=str(ref_audio))
    db_session.add(character)
    db_session.commit()
    db_session.refresh(character)

    chapter = Chapter(novel_id=novel.id, number=1, title="Chapter", content="content")
    db_session.add(chapter)
    db_session.commit()
    db_session.refresh(chapter)

    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="Shot",
        characters=json.dumps(["A"], ensure_ascii=False),
        scene="房间",
        props=json.dumps([], ensure_ascii=False),
        estimated_duration=4,
        duration=4,
    )
    db_session.add(shot)
    db_session.commit()
    db_session.refresh(shot)

    event = ShotAudioEvent(
        shot_id=shot.id,
        event_order=1,
        event_type="DIALOGUE",
        voice_owner_character_id=character.id,
        voice_owner_name="A",
        visible_speaker_name="A",
        requires_visible_lipsync=True,
        text="hello",
        emotion_prompt="自然",
        pause_after="NONE",
        tts_status="GENERATING",
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)

    workflow = Workflow(
        name="Audio workflow",
        type="audio",
        workflow_json="{}",
        is_active=True,
        node_mapping=json.dumps({"save_audio_node_id": "1"}),
    )
    db_session.add(workflow)
    db_session.commit()
    db_session.refresh(workflow)

    task = Task(
        type="audio_event_tts",
        status="running",
        name="TTS",
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        shot_id=shot.id,
        chapter_id=chapter.id,
        claim_token="token-a",
        worker_id="worker-a",
        heartbeat_at=datetime.utcnow(),
        metadata_json=json.dumps({"audio_event_id": event.id}),
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task, event, workflow


def test_atomic_claim_allows_only_one_worker(db_session):
    task = _create_task(db_session)
    repo = TaskRepository(db_session)

    first = repo.claim_pending_task("audio_event_tts", "worker-a")
    second = repo.claim_pending_task("audio_event_tts", "worker-b")

    assert first is not None
    assert first.id == task.id
    assert first.status == "running"
    assert first.worker_id == "worker-a"
    assert first.claim_token
    assert first.attempt == 1
    assert second is None


def test_recovery_does_not_reset_fresh_heartbeat(db_session):
    task = _create_task(db_session, status="running", heartbeat_at=datetime.utcnow(), claim_token="token-a", worker_id="worker-a")

    recovered = TaskRepository(db_session).recover_stale_running_tasks("audio_event_tts", stale_timeout_seconds=120)

    db_session.refresh(task)
    assert recovered == 0
    assert task.status == "running"
    assert task.claim_token == "token-a"


def test_recovery_resets_stale_heartbeat_to_pending(db_session):
    task = _create_task(db_session, status="running", heartbeat_at=datetime.utcnow() - timedelta(seconds=300), claim_token="token-a", worker_id="worker-a")

    recovered = TaskRepository(db_session).recover_stale_running_tasks("audio_event_tts", stale_timeout_seconds=120)

    db_session.refresh(task)
    metadata = json.loads(task.metadata_json)
    assert recovered == 1
    assert task.status == "pending"
    assert task.claim_token is None
    assert task.worker_id is None
    assert task.heartbeat_at is None
    assert metadata["recovered_from_stale_lease"] is True
    assert metadata["previous_worker_id"] == "worker-a"


def test_old_claim_token_cannot_write_after_reclaim(db_session):
    task = _create_task(db_session, status="running", heartbeat_at=datetime.utcnow(), claim_token="token-b", worker_id="worker-b")

    updated = TaskRepository(db_session).update_claimed_task(task.id, "token-a", {"status": "completed", "progress": 100})

    db_session.refresh(task)
    assert updated is False
    assert task.status == "running"
    assert task.claim_token == "token-b"
    assert task.progress in {None, 0}


def test_cancelled_task_rejects_late_heartbeat_and_writeback(db_session):
    task = _create_task(db_session, status="cancelled", heartbeat_at=datetime.utcnow(), claim_token="token-a", worker_id="worker-a")
    repo = TaskRepository(db_session)

    assert repo.heartbeat_task(task.id, "token-a") is False
    assert repo.update_claimed_task(task.id, "token-a", {"status": "completed"}) is False
    db_session.refresh(task)
    assert task.status == "cancelled"


def test_terminal_tasks_cannot_be_claimed(db_session):
    for status in ("completed", "failed", "cancelled"):
        _create_task(db_session, status=status)

    claimed = TaskRepository(db_session).claim_pending_task("audio_event_tts", "worker-a")

    assert claimed is None


def test_run_tts_task_requires_current_claim_before_comfy_submit(db_session, tmp_path, monkeypatch):
    task, event, workflow = _create_tts_fixture(db_session, tmp_path)

    class ForbiddenComfy:
        def __init__(self):
            raise AssertionError("ComfyUI should not be constructed without current claim")

    monkeypatch.setattr("app.services.audio_drive_service.ComfyUIService", ForbiddenComfy)
    monkeypatch.setattr("app.core.database.SessionLocal", lambda: db_session)

    task_id = task.id
    event_id = event.id
    workflow_id = workflow.id
    asyncio.run(AudioDriveService._run_tts_task(task_id, event_id, workflow_id, "stale-token"))

    task = db_session.query(Task).filter(Task.id == task_id).one()
    event = db_session.query(ShotAudioEvent).filter(ShotAudioEvent.id == event_id).one()
    assert task.status == "running"
    assert task.claim_token == "token-a"
    assert event.tts_status == "GENERATING"


def test_late_worker_after_reclaim_does_not_write_tts_asset(db_session, tmp_path, monkeypatch):
    task, event, workflow = _create_tts_fixture(db_session, tmp_path)
    output_audio = tmp_path / "out.wav"
    output_audio.write_bytes(b"wav")

    class FakeClient:
        async def upload_audio(self, _path):
            return {"success": True, "filename": "ref.wav"}

        async def queue_prompt(self, _workflow):
            return {"success": True, "prompt_id": "prompt-a"}

        async def wait_for_audio_result(self, *_args, **_kwargs):
            return {"success": True, "audio_url": str(output_audio), "duration": 1.2}

    class FakeBuilder:
        def build_audio_workflow(self, **_kwargs):
            return {"nodes": []}

    class FakeComfy:
        def __init__(self):
            self.client = FakeClient()
            self.builder = FakeBuilder()

    async def fake_download_audio(**_kwargs):
        task.claim_token = "token-b"
        task.worker_id = "worker-b"
        db_session.commit()
        return str(output_audio)

    monkeypatch.setattr("app.services.audio_drive_service.ComfyUIService", FakeComfy)
    monkeypatch.setattr("app.services.audio_drive_service.file_storage.download_audio", fake_download_audio)
    monkeypatch.setattr("app.services.audio_drive_service.url_to_local_path", lambda value: value)
    monkeypatch.setattr("app.core.database.SessionLocal", lambda: db_session)

    task_id = task.id
    event_id = event.id
    workflow_id = workflow.id
    asyncio.run(AudioDriveService._run_tts_task(task_id, event_id, workflow_id, "token-a"))

    task = db_session.query(Task).filter(Task.id == task_id).one()
    event = db_session.query(ShotAudioEvent).filter(ShotAudioEvent.id == event_id).one()
    assert task.status == "running"
    assert task.claim_token == "token-b"
    assert event.tts_status == "GENERATING"
    assert db_session.query(AudioEventTTSAsset).filter(AudioEventTTSAsset.audio_event_id == event_id).count() == 0
