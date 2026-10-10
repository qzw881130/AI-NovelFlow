import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.models.background_job import BackgroundJob
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.services import shot_video_service
from app.services.clip_result_recovery import INTERRUPTED_CLIP_ERROR, recover_completed_clip
from app.services.task_service import TaskService
from app.services.canonical_execution_invalidation import CanonicalExecutionConflict


@pytest.fixture
def execution(db_session, tmp_path, monkeypatch):
    novel = Novel(id="recovery-novel", title="Recovery")
    chapter = Chapter(id="recovery-chapter", novel_id=novel.id, number=1, title="Chapter")
    contract = {"capability": "GENERATE", "artifact_kind": "CLIP_ONLY",
                "clip": {"clip_index": 1, "clip_plan_revision": 2}}
    metadata = {"execution_scope": "CLIP", "clip_index": 1, "clip_plan_revision": 2,
                "capability": "GENERATE", "execution_contract": contract,
                "video_save_node_id": "169", "approval_status": "GENERATING"}
    graph = {"169": {"class_type": "SaveVideo", "inputs": {}}}
    shot = Shot(id="recovery-shot", chapter_id=chapter.id, index=1,
                video_url="/api/files/existing-final.mp4", video_status="completed",
                video_director_plan=json.dumps({"canonical_visual_plan": True, "clip_plan_revision": 2,
                    "clip_plan": [{"clip_index": 1, "capability": "GENERATE", "execution_status": "PLANNED"}]}))
    task = Task(id="recovery-task", name="C1", type="shot_video", status="running",
                novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
                comfyui_prompt_id="original-prompt", workflow_json=json.dumps(graph),
                metadata_json=json.dumps(metadata), created_at=datetime.utcnow() - timedelta(minutes=5),
                updated_at=datetime.utcnow() - timedelta(minutes=2))
    job = BackgroundJob(id="recovery-job", task_id=task.id, queue_name="shot_video",
                handler="app.services.shot_video_service:generate_shot_video_task", status="running", payload_json="{}")
    db_session.add_all([novel, chapter, shot, task, job])
    db_session.commit()
    history = {"prompt": [0, task.comfyui_prompt_id, graph],
               "outputs": {"169": {"videos": [{"filename": "original.mp4", "type": "output"}]}}}
    local = tmp_path / "recovered.mp4"
    local.write_bytes(b"original media")
    download = AsyncMock(return_value=str(local))
    monkeypatch.setattr(shot_video_service.file_storage, "download_video", download)
    monkeypatch.setattr(shot_video_service, "_probe_video_duration", lambda _: 8.0)
    service = TaskService(db_session)
    service.comfyui_service.get_queue_info = AsyncMock(return_value={"queue_running": [], "queue_pending": []})
    service.comfyui_service.client.get_prompt_state = AsyncMock(return_value={"state": "completed", "history": history})
    service.comfyui_service.client.queue_prompt = AsyncMock(side_effect=AssertionError("must not regenerate"))
    monkeypatch.setattr(service, "_recover_completed_shot_video_prompt", AsyncMock(side_effect=AssertionError("no legacy assembly")))
    return task, shot, history, service, download, local


@pytest.mark.asyncio
async def test_orphaned_generate_recovers_exact_clip_without_assembling_shot(execution, db_session):
    task, shot, _, service, download, _ = execution
    assert await service.reconcile_active_tasks([task]) == 1
    db_session.refresh(task)
    db_session.refresh(shot)
    assert task.status == "completed" and task.progress == 100
    assert task.error_message is None and task.comfyui_prompt_id == "original-prompt"
    assert json.loads(task.metadata_json)["approval_status"] == "APPROVED"
    clip = json.loads(shot.video_director_plan)["clip_plan"][0]
    assert clip["generated_by_task_id"] == task.id and clip["video_url"] == task.result_url
    # The old assembly becomes stale; the Clip must never become the final Shot.
    assert shot.video_url is None and shot.video_status == "pending"
    assert shot.video_url != task.result_url
    download.assert_awaited_once()
    service.comfyui_service.client.queue_prompt.assert_not_awaited()
    assert await service.reconcile_active_tasks() == 0


@pytest.mark.asyncio
async def test_old_interrupted_failure_is_recovered_on_default_reconciliation(execution, db_session):
    task, _, _, service, _, _ = execution
    task.status = "failed"
    task.error_message = INTERRUPTED_CLIP_ERROR
    db_session.commit()
    task.updated_at = datetime.utcnow() - timedelta(minutes=2)
    db_session.commit()
    assert await service.reconcile_active_tasks() == 1
    assert task.status == "completed" and task.error_message is None


@pytest.mark.asyncio
async def test_live_worker_keeps_ownership(execution, monkeypatch):
    task, _, _, service, download, _ = execution
    monkeypatch.setattr("app.services.background_workers.worker_manager.is_live", lambda _: True)
    assert await service.reconcile_active_tasks([task]) == 0
    assert task.status == "running"
    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_during_history_check_stays_cancelled(execution, db_session):
    task, _, history, service, download, _ = execution
    async def cancelled(*args, **kwargs):
        task.status = "cancelled"
        db_session.commit()
        return {"state": "completed", "history": history}
    service.comfyui_service.client.get_prompt_state.side_effect = cancelled
    await service.reconcile_active_tasks([task])
    assert task.status == "cancelled"
    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_overlapping_recovery_downloads_only_once(execution, db_session):
    task, _, history, service, download, local = execution
    entered, release = asyncio.Event(), asyncio.Event()
    async def waiting(*args, **kwargs):
        entered.set()
        await release.wait()
        return str(local)
    download.side_effect = waiting
    first = asyncio.create_task(recover_completed_clip(task, history, db_session, service.comfyui_service))
    await entered.wait()
    assert await recover_completed_clip(task, history, db_session, service.comfyui_service)
    release.set()
    assert await first
    download.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_during_download_does_not_fail_the_new_attempt(execution, db_session):
    task, _, _, service, download, local = execution
    async def retried(*args, **kwargs):
        task.comfyui_prompt_id = None
        task.status = "pending"
        db_session.commit()
        return str(local)
    download.side_effect = retried
    await service.reconcile_active_tasks([task])
    assert task.status == "pending" and task.comfyui_prompt_id is None
    assert task.error_message is None and task.result_url is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["receipt", "workflow", "revision", "owner", "cancelled", "superseded"])
async def test_stale_or_cancelled_receipts_never_write(execution, db_session, change):
    task, shot, history, service, download, _ = execution
    if change == "receipt":
        history["prompt"][1] = "different-prompt"
    elif change == "workflow":
        history["prompt"][2] = {"different": {}}
    elif change == "cancelled":
        task.status = "cancelled"
    elif change == "superseded":
        db_session.add(Task(id="new-attempt", type="shot_video", status="completed", name="new",
            shot_id=shot.id, metadata_json=task.metadata_json))
    else:
        plan = json.loads(shot.video_director_plan)
        if change == "revision":
            plan["clip_plan_revision"] = 3
        else:
            plan["clip_plan"][0]["generated_by_task_id"] = "new-owner"
        shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    with pytest.raises(CanonicalExecutionConflict):
        await recover_completed_clip(task, history, db_session, service.comfyui_service)
    download.assert_not_awaited()
    assert shot.video_url == "/api/files/existing-final.mp4"


def native_execution(task, shot, history, db_session):
    metadata = json.loads(task.metadata_json)
    metadata["capability"] = "EXTEND"
    metadata["execution_contract"].update(capability="EXTEND", artifact_kind="NATIVE_CONTINUITY_OUTPUT", previous_clip={"clip_index": 0})
    task.metadata_json = json.dumps(metadata)
    graph = {"65": {"class_type": "MiniMaxH3StreamLiveExtensionAVToVHS", "inputs": {}}}
    task.workflow_json = json.dumps(graph)
    history["prompt"][2] = graph
    plan = json.loads(shot.video_director_plan)
    plan["clip_plan"][0]["capability"] = "EXTEND"
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()


@pytest.mark.asyncio
async def test_native_recovery_never_promotes_raw_preview(execution, db_session):
    task, shot, history, service, download, _ = execution
    native_execution(task, shot, history, db_session)
    history["outputs"] = {"39": {"gifs": [{"filename": "preview-audio.mp4"}]}}
    assert not await recover_completed_clip(task, history, db_session, service.comfyui_service)
    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_recovery_reuses_av_validation_and_snapshot(execution, db_session, monkeypatch):
    task, shot, history, service, _, _ = execution
    native_execution(task, shot, history, db_session)
    history["outputs"] = {"65": {"gifs": [{"filename": "native-audio.mp4", "type": "output"}]}}
    previous_checks = []
    monkeypatch.setattr(shot_video_service, "resolve_extend_previous_av", lambda *args: previous_checks.append(args[-1]))
    mux = AsyncMock(return_value={"frames_after": 100})
    monkeypatch.setattr(shot_video_service, "preserve_native_av", mux)
    physical = {"physical_output_role": "NATIVE_CONTINUITY_OUTPUT", "output_node_id": "65"}
    monkeypatch.setattr(shot_video_service, "continuity_output_metadata", lambda *args: physical)
    assert await recover_completed_clip(task, history, db_session, service.comfyui_service)
    assert task.status == "completed"
    assert previous_checks == [{"clip_index": 0}, {"clip_index": 0}]
    mux.assert_awaited_once()
    assert json.loads(task.metadata_json)["physical_output"] == physical
    assert json.loads(shot.video_director_plan)["clip_plan"][0]["physical_output"] == physical


@pytest.mark.asyncio
async def test_revision_change_during_download_is_rejected(execution, db_session):
    task, shot, history, service, download, local = execution
    async def changed(*args, **kwargs):
        plan = json.loads(shot.video_director_plan)
        plan["clip_plan_revision"] = 3
        shot.video_director_plan = json.dumps(plan)
        db_session.commit()
        return str(local)
    download.side_effect = changed
    with pytest.raises(CanonicalExecutionConflict):
        await recover_completed_clip(task, history, db_session, service.comfyui_service)
    assert not local.exists()
    assert task.result_url is None and shot.video_url == "/api/files/existing-final.mp4"
