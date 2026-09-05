import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import shots as api
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.repositories import ChapterRepository, NovelRepository, ShotRepository


@pytest.fixture
def batch(db_session, monkeypatch):
    novel = Novel(title="Batch failures")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="Chapter", content="content")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id, index=1, description="Shot", duration=4,
        video_status="pending", video_director_plan=json.dumps({"clips": [{"video_url": "old-clip.mp4"}]}),
    )
    db_session.add(shot)
    db_session.commit()
    monkeypatch.setattr(api, "SessionLocal", lambda: db_session)

    def submit():
        response = asyncio.run(api.generate_shot_videos_batch(
            novel.id, chapter.id, api.BatchShotVideoRequest(shot_ids=[shot.id]),
            novel_repo=NovelRepository(db_session), chapter_repo=ChapterRepository(db_session),
            shot_repo=ShotRepository(db_session), db=db_session,
        ))
        return response["data"]["taskId"]

    return shot, submit


@pytest.mark.parametrize("stage", ["prepare", "generate"])
@pytest.mark.parametrize("error", [HTTPException(400, "Missing workflow"), RuntimeError("Clip audio unavailable"), TimeoutError()])
def test_preflight_failure_persists_without_child(db_session, monkeypatch, batch, stage, error):
    shot, submit = batch
    shot_id = shot.id
    parent_id = submit()
    assert shot.video_task_id == parent_id
    assert shot.video_status == "pending"
    prepare = AsyncMock(return_value="SINGLE_FRAME")
    generate = AsyncMock()
    (prepare if stage == "prepare" else generate).side_effect = error
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", prepare)
    monkeypatch.setattr(api, "generate_shot_video", generate)

    asyncio.run(api.run_shot_video_batch_task(parent_id))

    shot = db_session.get(Shot, shot_id)
    parent = db_session.get(Task, parent_id)
    message = str(error.detail) if isinstance(error, HTTPException) else str(error) or type(error).__name__
    assert shot.video_status == "failed"
    assert shot.video_task_id == parent_id
    plan = json.loads(shot.video_director_plan)
    assert plan["error_message"] == plan["task_error_message"] == message
    assert plan["clips"] == [{"video_url": "old-clip.mp4"}]
    assert shot.video_director_plan_revision == 1
    assert json.loads(parent.metadata_json)["results"][shot_id]["message"] == message
    assert parent.status == "failed"
    assert db_session.query(Task).filter(Task.type == "shot_video").count() == 0


def test_legacy_unbound_pending_shot_is_claimed(db_session, monkeypatch, batch):
    shot, submit = batch
    shot_id = shot.id
    parent_id = submit()
    shot.video_task_id = None
    db_session.commit()
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", AsyncMock(side_effect=RuntimeError("preflight")))
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert (shot.video_status, shot.video_task_id) == ("failed", parent_id)


@pytest.mark.parametrize("raise_error", [True, False])
def test_new_owner_during_preflight_is_not_overwritten(db_session, monkeypatch, batch, raise_error):
    shot, submit = batch
    shot_id = shot.id
    parent_id = submit()

    async def prepare(*args, **kwargs):
        shot.video_task_id = "new-task"
        shot.video_status = "generating"
        shot.video_director_plan = '{"new_plan": true}'
        db_session.commit()
        if raise_error:
            raise RuntimeError("old preflight")
        return "SINGLE_FRAME"

    generate = AsyncMock()
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", prepare)
    monkeypatch.setattr(api, "generate_shot_video", generate)
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert (shot.video_status, shot.video_task_id) == ("generating", "new-task")
    assert json.loads(shot.video_director_plan) == {"new_plan": True}
    generate.assert_not_awaited()


def test_historical_video_survives_failed_replacement(db_session, monkeypatch, batch):
    shot, submit = batch
    shot_id = shot.id
    shot.video_status = "completed"
    shot.video_url = "/api/files/historical.mp4"
    db_session.commit()
    parent_id = submit()
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", AsyncMock(side_effect=RuntimeError("preflight")))
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert shot.video_status == "completed"
    assert shot.video_url == "/api/files/historical.mp4"
    assert json.loads(shot.video_director_plan)["task_error_message"] == "preflight"


def test_active_child_not_rebound_by_batch_creation(db_session, monkeypatch, batch):
    shot, submit = batch
    shot_id = shot.id
    chapter = db_session.get(Chapter, shot.chapter_id)
    child = Task(type="shot_video", status="running", name="child", shot_id=shot.id,
                 novel_id=chapter.novel_id, chapter_id=chapter.id)
    db_session.add(child)
    db_session.flush()
    child_id = child.id
    shot.video_task_id = child_id
    shot.video_status = "generating"
    db_session.commit()
    parent_id = submit()
    assert shot.video_task_id == child_id
    prepare = AsyncMock()
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", prepare)
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert (shot.video_status, shot.video_task_id) == ("generating", child_id)
    assert db_session.get(Task, child_id).parent_task_id is None
    prepare.assert_not_awaited()


@pytest.mark.parametrize("child_status", [None, "failed", "completed"])
def test_child_outcome_and_ownership_handoff(db_session, monkeypatch, batch, child_status):
    shot, submit = batch
    shot_id = shot.id
    parent_id = submit()
    child_id = None

    async def generate(*args, **kwargs):
        nonlocal child_id
        if child_status is None:
            return {"data": {}}
        child = Task(type="shot_video", status=child_status, name="child", shot_id=shot.id,
                     error_message="Child failed" if child_status == "failed" else None)
        db_session.add(child)
        db_session.flush()
        child_id = child.id
        shot.video_task_id = child.id
        shot.video_status = "completed" if child_status == "completed" else "generating"
        if child_status == "completed":
            shot.video_url = "/api/files/new.mp4"
        db_session.commit()
        return {"data": {"taskId": child.id}}

    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", AsyncMock(return_value="SINGLE_FRAME"))
    monkeypatch.setattr(api, "generate_shot_video", generate)
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert shot.video_task_id == (child_id or parent_id)
    assert shot.video_status == ("completed" if child_status == "completed" else "failed")
    if child_id:
        assert db_session.get(Task, child_id).parent_task_id == parent_id
    plan = json.loads(shot.video_director_plan)
    assert ("task_error_message" in plan) == (child_status != "completed")


def test_completed_batch_persists_all_fourteen_preflight_failures(db_session, monkeypatch, batch):
    shot, submit = batch
    parent_id = submit()
    failed_shots = [
        Shot(chapter_id=shot.chapter_id, index=index, description="Preflight failure", duration=4,
             video_task_id=parent_id, video_status="pending")
        for index in range(2, 16)
    ]
    db_session.add_all(failed_shots)
    db_session.flush()
    failed_ids = [item.id for item in failed_shots]
    parent = db_session.get(Task, parent_id)
    metadata = json.loads(parent.metadata_json)
    metadata["shot_ids"] += failed_ids
    metadata["results"] = {shot.id: {"status": "completed"}}
    parent.metadata_json = json.dumps(metadata)
    shot.video_status = "completed"
    shot.video_url = "/api/files/success.mp4"
    db_session.commit()
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", AsyncMock(side_effect=RuntimeError("Missing clip audio")))

    asyncio.run(api.run_shot_video_batch_task(parent_id))

    parent = db_session.get(Task, parent_id)
    metadata = json.loads(parent.metadata_json)
    assert parent.status == "completed"
    assert (metadata["success_count"], metadata["failed_count"]) == (1, 14)
    for shot_id in failed_ids:
        failed_shot = db_session.get(Shot, shot_id)
        assert failed_shot.video_status == "failed"
        assert failed_shot.video_task_id == parent_id
        assert json.loads(failed_shot.video_director_plan)["task_error_message"] == "Missing clip audio"
        assert metadata["results"][shot_id]["status"] == "failed"


def test_outer_batch_failure_releases_parent_owned_shots(db_session, monkeypatch, batch):
    shot, submit = batch
    shot_id = shot.id
    parent_id = submit()
    def fail_setup(db):
        raise RuntimeError("Batch setup failed")

    monkeypatch.setattr(api, "NovelRepository", fail_setup)
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert shot.video_status == "failed"
    assert json.loads(shot.video_director_plan)["task_error_message"] == "Batch setup failed"
    assert db_session.get(Task, parent_id).status == "failed"


def test_failure_does_not_replace_completed_shot_or_plan(db_session, batch):
    shot, submit = batch
    parent_id = submit()
    shot.video_status = "completed"
    shot.video_url = "/api/files/completed.mp4"
    db_session.commit()
    previous_plan = shot.video_director_plan
    previous_revision = shot.video_director_plan_revision

    api._persist_batch_video_failure(db_session, shot.id, parent_id, "Late failure")
    db_session.commit()
    db_session.refresh(shot)

    assert shot.video_status == "completed"
    assert shot.video_url == "/api/files/completed.mp4"
    assert shot.video_director_plan == previous_plan
    assert shot.video_director_plan_revision == previous_revision
