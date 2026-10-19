import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import Session

from app.models.novel import Chapter, Novel
from app.models.background_job import BackgroundJob
from app.models.shot import Shot
from app.models.task import Task
from app.services.task_service import TaskService


@pytest.mark.asyncio
async def test_clip_only_reconciliation_does_not_recover_or_assemble(db_session, monkeypatch):
    novel = Novel(id="novel-reconcile", title="Reconcile")
    chapter = Chapter(id="chapter-reconcile", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(
        id="shot-reconcile",
        chapter_id=chapter.id,
        index=4,
        duration=8,
        video_url="/api/files/final.mp4",
        video_status="completed",
        video_director_plan=json.dumps({
            "clip_plan_revision": 3,
            "clip_plan": [{"clip_index": 1, "capability": "MULTI_KEYFRAME"}],
        }),
    )
    task = Task(
        id="clip-only-running",
        type="shot_video",
        status="running",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        name="Clip C1",
        comfyui_prompt_id="comfy-prompt",
        metadata_json=json.dumps({
            "execution_scope": "CLIP",
            "clip_index": 1,
            "clip_plan_revision": 3,
            "execution_contract": {
                "capability": "GENERATE",
                "artifact_kind": "CLIP_ONLY",
            },
        }),
    )
    db_session.add_all([novel, chapter, shot, task])
    db_session.commit()

    service = TaskService(db_session)
    service.comfyui_service.get_queue_info = AsyncMock(return_value={"queue_running": [], "queue_pending": []})
    service.comfyui_service.client.get_prompt_state = AsyncMock(return_value={
        "state": "completed",
        "history": {"outputs": {"169": {}}},
    })
    recovery = AsyncMock(side_effect=AssertionError("CLIP_ONLY must not enter legacy recovery"))
    monkeypatch.setattr(service, "_recover_completed_shot_video_prompt", recovery)

    updated = await service.reconcile_active_tasks([task], db=db_session)

    db_session.refresh(task)
    db_session.refresh(shot)
    assert updated == 0
    assert task.status == "running"
    assert task.error_message is None
    assert shot.video_status == "completed"
    assert shot.video_url == "/api/files/final.mp4"
    recovery.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_reconciliation_still_marks_shot_failed(db_session):
    novel = Novel(id="novel-legacy-reconcile", title="Reconcile")
    chapter = Chapter(id="chapter-legacy-reconcile", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(id="shot-legacy-reconcile", chapter_id=chapter.id, index=1, video_status="generating")
    task = Task(
        id="legacy-running",
        type="shot_video",
        status="running",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        name="Legacy video",
        started_at=datetime.utcnow() - timedelta(seconds=601),
        current_step="正在调用 ComfyUI 生成视频...",
        metadata_json=json.dumps({"execution_scope": "CLIP", "capability": "SINGLE_FRAME"}),
    )
    db_session.add_all([novel, chapter, shot, task])
    db_session.commit()

    service = TaskService(db_session)
    service.comfyui_service.get_queue_info = AsyncMock(return_value={"queue_running": [], "queue_pending": []})

    await service.reconcile_active_tasks([task], db=db_session)

    db_session.refresh(shot)
    assert task.status == "failed"
    assert shot.video_status == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("live", [True, False])
async def test_missing_prompt_does_not_fail_clip_while_worker_can_finish(db_session, monkeypatch, live):
    task = Task(
        id=f"clip-missing-{live}", type="shot_video", status="running", name="Clip C1",
        comfyui_prompt_id="submitted-prompt",
        created_at=datetime.utcnow() - timedelta(minutes=5),
        started_at=datetime.utcnow() - timedelta(minutes=5),
        updated_at=datetime.utcnow() - timedelta(minutes=2),
        metadata_json=json.dumps({
            "execution_scope": "CLIP",
            "execution_contract": {"artifact_kind": "CLIP_ONLY"},
        }),
    )
    job = BackgroundJob(
        id=f"clip-job-{live}", task_id=task.id, queue_name="shot_video",
        handler="app.services.shot_video_service:generate_shot_video_task",
        status="running", payload_json="{}",
    )
    db_session.add_all([task, job])
    db_session.commit()
    monkeypatch.setattr("app.services.background_workers.worker_manager.is_live", lambda _: live)
    service = TaskService(db_session)
    service.comfyui_service.get_queue_info = AsyncMock(return_value={"queue_running": [], "queue_pending": []})
    service.comfyui_service.client.get_prompt_state = AsyncMock(return_value={"state": "missing"})

    assert await service.reconcile_active_tasks([task], db=db_session) == 0
    db_session.refresh(task)
    assert task.status == "running" and task.error_message is None


@pytest.mark.asyncio
async def test_missing_prompt_fails_after_worker_timeout(db_session, monkeypatch):
    task = Task(
        id="clip-stale-missing", type="shot_video", status="running", name="Clip C1",
        comfyui_prompt_id="lost-prompt",
        created_at=datetime.utcnow() - timedelta(hours=1),
        started_at=datetime.utcnow() - timedelta(hours=1),
        updated_at=datetime.utcnow() - timedelta(hours=1),
    )
    job = BackgroundJob(
        id="clip-stale-job", task_id=task.id, queue_name="shot_video",
        handler="app.services.shot_video_service:generate_shot_video_task",
        status="running", payload_json="{}",
    )
    db_session.add_all([task, job])
    db_session.commit()
    monkeypatch.setattr("app.services.background_workers.worker_manager.is_live", lambda _: False)
    service = TaskService(db_session)
    service.comfyui_service.get_queue_info = AsyncMock(return_value={"queue_running": [], "queue_pending": []})
    service.comfyui_service.client.get_prompt_state = AsyncMock(return_value={"state": "missing"})

    assert await service.reconcile_active_tasks([task], db=db_session) == 1
    db_session.refresh(task)
    assert task.status == "failed"


@pytest.mark.asyncio
async def test_missing_prompt_does_not_overwrite_worker_completion(db_session):
    task = Task(
        id="clip-completes-during-lookup", type="shot_video", status="running", name="Clip C1",
        comfyui_prompt_id="finished-prompt",
        created_at=datetime.utcnow() - timedelta(hours=1),
        started_at=datetime.utcnow() - timedelta(hours=1),
    )
    db_session.add(task)
    db_session.commit()
    service = TaskService(db_session)
    service.comfyui_service.get_queue_info = AsyncMock(return_value={"queue_running": [], "queue_pending": []})

    async def complete_during_lookup(*args, **kwargs):
        with Session(db_session.bind) as worker_db:
            worker_task = worker_db.get(Task, task.id)
            worker_task.status = "completed"
            worker_task.result_url = "/api/files/clip.mp4"
            worker_db.commit()
        return {"state": "missing"}

    service.comfyui_service.client.get_prompt_state = AsyncMock(side_effect=complete_during_lookup)
    assert await service.reconcile_active_tasks([task], db=db_session) == 0
    db_session.refresh(task)
    assert task.status == "completed" and task.result_url == "/api/files/clip.mp4"
