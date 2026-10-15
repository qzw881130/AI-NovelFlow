"""Explicit retry through real persist -> run_persisted, with no network/media.

Only the expensive video handler is substituted. TaskService, enqueue,
WorkerManager and Previous AV provenance validation use their real code.
"""
import asyncio
import json
from copy import deepcopy

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.constants.capability import EXTEND_WORKFLOW_ID, TEMPORAL_EXTEND_WORKFLOW_ID
from app.models.background_job import BackgroundJob
from app.models.task import Task
from app.models.workflow import Workflow
from app.services import background_workers, shot_video_service as video
from app.services.background_workers import WorkerManager
from app.services.task_service import TaskService
from test_extend_previous_av import _state
from test_continuous_clip_native_av import physical


@pytest.fixture
def setup_retry(db_session, db_engine, tmp_path, monkeypatch):
    manager = WorkerManager(sessionmaker(bind=db_engine, autoflush=False))
    monkeypatch.setattr(background_workers, "worker_manager", manager)
    monkeypatch.setattr(video, "worker_manager", manager)
    monkeypatch.setattr(video, "_queued_shot_video_task_ids", set())
    # Fail closed if any test accidentally reaches a real external generator.
    async def forbidden(*args, **kwargs):
        pytest.fail("external generation is forbidden")
    monkeypatch.setattr("app.services.llm_service.LLMService.chat_completion", forbidden)
    monkeypatch.setattr("app.services.comfyui.client.ComfyUIClient.queue_prompt", forbidden)

    def create(mode="GENERATE", route="phase_b", clip_only=True):
        novel, chapter, shot, previous, artifact = _state(tmp_path)
        wf_type = {"GENERATE": "multi_reference_video", "EXTEND": "VIDEO_CONTINUATION",
                   "TEMPORAL_EXTEND": "TEMPORAL_EXTEND"}[mode]
        wf_id = {"EXTEND": EXTEND_WORKFLOW_ID, "TEMPORAL_EXTEND": TEMPORAL_EXTEND_WORKFLOW_ID}.get(mode, "generate-workflow")
        meta = {
            "execution_scope": "CLIP", "clip_id": f"{shot.id}:clip:2", "clip_index": 2,
            "clip_plan_revision": 4, "capability": mode, "h3_prompt_pipeline": route,
            "planned_duration": 8, "requested_duration": 10.8,
            "dialogue_assignment": [{"dialogue_id": "D27", "speaker": "speaker-2", "text": "原文"}],
            "execution_contract": {"previous_clip": {
                "clip_index": 1, "clip_plan_revision": 4,
                "generated_by_task_id": previous.id, "result_url": previous.result_url,
            }},
        } if clip_only else {"legacy": "metadata"}
        task = Task(id="retry-video", type="shot_video", name="retry", status="pending",
                    novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
                    workflow_id=wf_id, metadata_json=json.dumps(meta, ensure_ascii=False))
        db_session.add_all([novel, chapter, shot, previous, task, Workflow(
            id=wf_id, type=wf_type, name="frozen", workflow_json="{}", is_active=True,
        )]); db_session.commit()
        monkeypatch.setattr(video, "url_to_local_path", lambda _: str(artifact))
        monkeypatch.setattr(video, "probe_clip_av", lambda _: physical(209, artifact.read_bytes()))
        args = (task.id, novel.id, chapter.id, shot.index, wf_id, shot.image_url or "")
        options = dict(selected_mode="MULTI_KEYFRAME", use_keyframes=False,
                       use_reference_audio=False, only_window_index=2, auto_merge_clips=True,
                       skip_llm_when_prompt_exists=True, optimize_h3_prompt=route != "phase_b")
        if clip_only:
            options["clip_metadata"] = meta
        return task, shot, previous, artifact, args, options

    return manager, create


def install_handler(monkeypatch, db_engine, *, fail_first=False, entered=None, finish=None):
    calls = []
    sessions = sessionmaker(bind=db_engine)
    async def handler(task_id, *args, **kwargs):
        calls.append((args, deepcopy(kwargs)))
        if entered:
            entered.set()
        if finish:
            await finish.wait()
        if fail_first and len(calls) == 1:
            raise RuntimeError("offline handler failure")
        with sessions() as db:
            task = db.get(Task, task_id)
            if task.status == "cancelled":
                return
            task.status = "completed"
            task.result_url = f"/offline-result-{len(calls)}.mp4"
            task.comfyui_prompt_id = f"offline-receipt-{len(calls)}"
            task.workflow_json = '{"frozen":true}'
            task.prompt_text = "saved prompt"
            task.seed = 123
            db.commit()
    monkeypatch.setattr(video, "generate_shot_video_task", handler)
    return calls


async def drained(manager):
    await asyncio.wait_for(manager.worker("shot_video")._queue.join(), 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["phase_b", "legacy"])
@pytest.mark.parametrize("mode", ["GENERATE", "EXTEND", "TEMPORAL_EXTEND"])
@pytest.mark.parametrize("fail_first", [False, True])
async def test_first_run_and_explicit_retry_consumed_once(
    setup_retry, db_session, db_engine, monkeypatch, route, mode, fail_first,
):
    manager, create = setup_retry
    task, shot, _, _, args, options = create(mode, route)
    calls = install_handler(monkeypatch, db_engine, fail_first=fail_first)
    try:
        video.enqueue_shot_video_task(*args, **options)
        video.enqueue_shot_video_task(*args, **options)
        await drained(manager)
        db_session.expire_all()
        old = db_session.query(BackgroundJob).one()
        old_snapshot = (old.id, old.status, old.payload_json, old.attempts, old.completed_at)
        assert old.status == ("failed" if fail_first else "completed")
        assert old.attempts == 1 and len(calls) == 1
        metadata = json.loads(task.metadata_json)
        previous_result = task.result_url
        assert TaskService(db_session).retry_task(task.id)["success"]
        assert not TaskService(db_session).retry_task(task.id)["success"]
        # Ordinary repeated enqueue during the new attempt cannot create a third job.
        video.enqueue_shot_video_task(*args, **options)
        await drained(manager)
        db_session.expire_all()
        jobs = db_session.query(BackgroundJob).all()
        assert len(jobs) == 2 and len(calls) == 2
        assert task.status == "completed"
        assert (old.id, old.status, old.payload_json, old.attempts, old.completed_at) == old_snapshot
        current = next(job for job in jobs if job.id != old.id)
        assert current.status == "completed" and current.attempts == 1
        assert all(calls[1][1][key] == value for key, value in options.items() if key != "clip_metadata")
        retried_meta = json.loads(task.metadata_json)
        assert all(retried_meta[key] == value for key, value in metadata.items())
        assert retried_meta["background_job_history"][0]["result_url"] == previous_result
        assert calls[1][1]["clip_metadata"]["h3_prompt_pipeline"] == route
        assert shot.video_url == "/api/files/shot-final.mp4"
        # A terminal retry descriptor remains terminal on ordinary enqueue or restart.
        video.enqueue_shot_video_task(*args, **options)
        await drained(manager)
        restarted = WorkerManager(sessionmaker(bind=db_engine))
        assert restarted.resume_persisted() == 0
        assert db_session.query(BackgroundJob).count() == 2 and len(calls) == 2
        # A subsequent *explicit* retry is a third historical attempt, not revival.
        assert TaskService(db_session).retry_task(task.id)["success"]
        await drained(manager)
        db_session.expire_all()
        assert len(calls) == 3 and db_session.query(BackgroundJob).count() == 3
        assert len(json.loads(task.metadata_json)["background_job_history"]) == 2
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_legacy_shot_level_retry_uses_real_queue(setup_retry, db_session, db_engine, monkeypatch):
    manager, create = setup_retry
    task, shot, _, _, args, options = create(clip_only=False)
    calls = install_handler(monkeypatch, db_engine)
    try:
        video.enqueue_shot_video_task(*args, **options); await drained(manager)
        db_session.expire_all()
        assert TaskService(db_session).retry_task(task.id)["success"]
        await drained(manager); db_session.expire_all()
        assert len(calls) == 2 and db_session.query(BackgroundJob).count() == 2
        assert calls[1][1]["clip_metadata"] is None
        assert shot.video_url is None and shot.video_status == "generating"
        assert json.loads(task.metadata_json)["legacy"] == "metadata"
    finally:
        await manager.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["GENERATE", "EXTEND", "TEMPORAL_EXTEND"])
async def test_unresolved_receipt_blocks_retry_and_restart(setup_retry, db_session, db_engine, monkeypatch, mode):
    manager, create = setup_retry
    task, _, _, _, args, options = create(mode)
    calls = install_handler(monkeypatch, db_engine)
    try:
        video.enqueue_shot_video_task(*args, **options); await drained(manager)
        db_session.expire_all()
        task.status = "failed"
        task.error_message = "download interrupted, GPU outcome unresolved"
        task.result_url = None
        db_session.commit()
        before = (task.metadata_json, task.comfyui_prompt_id, task.workflow_json)
        result = TaskService(db_session).retry_task(task.id)
        assert not result["success"] and result["status_code"] == 409
        assert (task.metadata_json, task.comfyui_prompt_id, task.workflow_json) == before
        assert manager.resume_persisted() == 0
        assert len(calls) == 1 and db_session.query(BackgroundJob).count() == 1
    finally:
        await manager.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["phase_b", "legacy"])
@pytest.mark.parametrize("mode", ["EXTEND", "TEMPORAL_EXTEND"])
@pytest.mark.parametrize("invalid", ["approval", "missing_file", "revision"])
async def test_retry_revalidates_original_previous_av(setup_retry, db_session, db_engine, monkeypatch, route, mode, invalid):
    manager, create = setup_retry
    task, shot, previous, artifact, args, options = create(mode, route)
    calls = install_handler(monkeypatch, db_engine)
    try:
        video.enqueue_shot_video_task(*args, **options); await drained(manager)
        db_session.expire_all()
        if invalid == "approval":
            previous.status = "failed"
        elif invalid == "missing_file":
            artifact.unlink()
        else:
            plan = json.loads(shot.video_director_plan); plan["clip_plan_revision"] += 1
            shot.video_director_plan = json.dumps(plan)
        db_session.commit()
        result = TaskService(db_session).retry_task(task.id)
        assert not result["success"] and result["status_code"] == 409
        assert len(calls) == 1 and db_session.query(BackgroundJob).count() == 1
        assert "background_job_attempt" not in json.loads(task.metadata_json)
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_duplicate_retry_with_stale_session_cannot_reset_running_attempt(setup_retry, db_session, db_engine, monkeypatch):
    manager, create = setup_retry
    task, _, _, _, args, options = create()
    calls = install_handler(monkeypatch, db_engine)
    stale_db = sessionmaker(bind=db_engine)()
    try:
        video.enqueue_shot_video_task(*args, **options); await drained(manager)
        db_session.expire_all()
        stale = stale_db.get(Task, task.id)
        assert stale.status == "completed"
        entered, finish = asyncio.Event(), asyncio.Event()
        retry_calls = install_handler(monkeypatch, db_engine, entered=entered, finish=finish)
        assert TaskService(db_session).retry_task(task.id)["success"]
        await asyncio.wait_for(entered.wait(), 1)
        assert not TaskService(stale_db).retry_task(task.id)["success"]
        assert len(calls) == len(retry_calls) == 1
        assert db_session.query(BackgroundJob).count() == 2
        finish.set(); await drained(manager)
    finally:
        stale_db.close(); await manager.stop()


@pytest.mark.asyncio
async def test_cancel_queued_retry_never_runs_handler(setup_retry, db_session, db_engine, monkeypatch):
    manager, create = setup_retry
    task, _, _, _, args, options = create()
    calls = install_handler(monkeypatch, db_engine)
    try:
        video.enqueue_shot_video_task(*args, **options); await drained(manager)
        db_session.expire_all()
        assert TaskService(db_session).retry_task(task.id)["success"]
        assert (await TaskService(db_session).cancel_task(task.id))["success"]
        await drained(manager); db_session.expire_all()
        assert task.status == "cancelled" and len(calls) == 1
        assert db_session.query(BackgroundJob).count() == 2
        assert manager.resume_persisted() == 0
        assert not TaskService(db_session).retry_task(task.id)["success"]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_retry_transaction_rolls_back_if_descriptor_cannot_persist(setup_retry, db_session, db_engine, monkeypatch):
    manager, create = setup_retry
    task, _, _, _, args, options = create()
    install_handler(monkeypatch, db_engine)
    try:
        video.enqueue_shot_video_task(*args, **options); await drained(manager)
        db_session.expire_all()
        before = (task.status, task.metadata_json, task.comfyui_prompt_id, task.result_url)
        def fail(*args, **kwargs):
            raise RuntimeError("offline storage failure")
        event.listen(BackgroundJob, "before_insert", fail)
        try:
            with pytest.raises(RuntimeError, match="offline storage failure"):
                TaskService(db_session).retry_task(task.id)
        finally:
            event.remove(BackgroundJob, "before_insert", fail)
        db_session.refresh(task)
        assert (task.status, task.metadata_json, task.comfyui_prompt_id, task.result_url) == before
        assert db_session.query(BackgroundJob).count() == 1
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_restart_consumes_only_new_queued_retry(setup_retry, db_session, db_engine, monkeypatch):
    manager, create = setup_retry
    task, _, _, _, args, options = create()
    calls = install_handler(monkeypatch, db_engine)
    try:
        video.enqueue_shot_video_task(*args, **options); await drained(manager)
        db_session.expire_all()
        monkeypatch.setattr(manager.worker("shot_video"), "signal", lambda _: None)
        assert TaskService(db_session).retry_task(task.id)["success"]
        db_session.expire_all()
        queued = db_session.query(BackgroundJob).filter_by(status="queued").one()
        restarted = WorkerManager(sessionmaker(bind=db_engine))
        try:
            assert restarted.resume_persisted() == 1
            await drained(restarted)
            db_session.expire_all()
            assert queued.status == "completed" and queued.attempts == 1
            assert len(calls) == 2 and restarted.resume_persisted() == 0
        finally:
            await restarted.stop()
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_completed_job_with_failed_task_and_no_receipt_can_retry(setup_retry, db_session, db_engine, monkeypatch):
    manager, create = setup_retry
    task, _, _, _, args, options = create()
    calls = install_handler(monkeypatch, db_engine)
    try:
        video.enqueue_shot_video_task(*args, **options); await drained(manager)
        db_session.expire_all()
        task.status = "failed"
        task.result_url = task.comfyui_prompt_id = None
        db_session.commit()
        assert db_session.query(BackgroundJob).one().status == "completed"
        assert TaskService(db_session).retry_task(task.id)["success"]
        await drained(manager)
        assert len(calls) == 2 and db_session.query(BackgroundJob).count() == 2
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_active_job_blocks_retry_even_if_task_was_marked_terminal(setup_retry, db_session, db_engine, monkeypatch):
    manager, create = setup_retry
    task, _, _, _, args, options = create()
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = install_handler(monkeypatch, db_engine, entered=entered, finish=finish)
    try:
        video.enqueue_shot_video_task(*args, **options)
        await asyncio.wait_for(entered.wait(), 1)
        db_session.refresh(task)
        task.status = "failed"; db_session.commit()
        result = TaskService(db_session).retry_task(task.id)
        assert not result["success"] and result["status_code"] == 409
        assert len(calls) == 1 and db_session.query(BackgroundJob).count() == 1
        finish.set(); await drained(manager)
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_receipt_appears_before_retry_worker_claim_no_resubmission(setup_retry, db_session, db_engine, monkeypatch):
    manager, create = setup_retry
    task, _, _, _, args, options = create()
    calls = install_handler(monkeypatch, db_engine)
    try:
        video.enqueue_shot_video_task(*args, **options); await drained(manager)
        db_session.expire_all()
        assert TaskService(db_session).retry_task(task.id)["success"]
        task.comfyui_prompt_id = "already-submitted"
        db_session.commit()
        await drained(manager)
        assert len(calls) == 1
        assert manager.resume_persisted() == 0
        db_session.expire_all()
        queued = db_session.query(BackgroundJob).filter_by(status="queued").one()
        assert queued.attempts == 0
        assert task.comfyui_prompt_id == "already-submitted"
    finally:
        await manager.stop()
