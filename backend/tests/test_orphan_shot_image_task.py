"""A finished batch must not leave an unfinished shot image spinning forever."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.background_job import BackgroundJob
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.services.task_service import TaskService
from app.services.background_workers import worker_manager


@pytest.mark.asyncio
async def test_finished_batch_reconciles_orphan_child_and_current_shot(db_session):
    novel = Novel(title="残留任务")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="章")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=3, description="镜3", image_status="generating")
    db_session.add(shot)
    db_session.flush()
    batch = Task(type="shot_image_batch", name="批量", status="failed", novel_id=novel.id, chapter_id=chapter.id)
    db_session.add(batch)
    db_session.flush()
    child = Task(type="shot_image", name="镜3", status="pending", novel_id=novel.id,
                 chapter_id=chapter.id, shot_id=shot.id, parent_task_id=batch.id)
    db_session.add(child)
    db_session.flush()
    shot.image_task_id = child.id
    db_session.add(BackgroundJob(task_id=child.id, queue_name="shot_image", handler="test:run",
                                 payload_json="{}", status="completed"))
    db_session.commit()

    service = TaskService(db_session)
    service.comfyui_service = SimpleNamespace(get_queue_info=AsyncMock(return_value={}))
    assert await service.reconcile_active_tasks([child], db_session) == 1

    db_session.refresh(child)
    db_session.refresh(shot)
    assert child.status == shot.image_status == "failed"
    assert child.completed_at is not None
    assert "批量任务已结束" in child.error_message


@pytest.mark.asyncio
async def test_orphan_reconciliation_does_not_mark_newer_shot_attempt_failed(db_session):
    novel = Novel(title="保留新任务")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="章")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=3, description="镜3", image_status="generating",
                image_task_id="new-attempt")
    db_session.add(shot)
    db_session.flush()
    batch = Task(type="shot_image_batch", name="旧批量", status="failed", novel_id=novel.id, chapter_id=chapter.id)
    db_session.add(batch)
    db_session.flush()
    child = Task(type="shot_image", name="旧镜3", status="pending", novel_id=novel.id,
                 chapter_id=chapter.id, shot_id=shot.id, parent_task_id=batch.id)
    db_session.add(child)
    db_session.commit()

    service = TaskService(db_session)
    service.comfyui_service = SimpleNamespace(get_queue_info=AsyncMock(return_value={}))
    assert await service.reconcile_active_tasks([child], db_session) == 1
    db_session.refresh(shot)
    assert shot.image_status == "generating"


@pytest.mark.asyncio
async def test_finished_batch_does_not_interrupt_live_child(db_session, monkeypatch):
    batch = Task(type="shot_image_batch", name="批量", status="failed")
    db_session.add(batch)
    db_session.flush()
    child = Task(type="shot_image", name="仍在运行", status="running", parent_task_id=batch.id)
    db_session.add(child)
    db_session.flush()
    db_session.add(BackgroundJob(task_id=child.id, queue_name="shot_image", handler="test:run",
                                 payload_json="{}", status="running"))
    db_session.commit()
    monkeypatch.setattr(worker_manager, "is_live", lambda _: True)

    service = TaskService(db_session)
    service.comfyui_service = SimpleNamespace(get_queue_info=AsyncMock(return_value={}))
    assert await service.reconcile_active_tasks([child], db_session) == 0
    db_session.refresh(child)
    assert child.status == "running"
