"""Accept an existing C1 video without erasing its cancelled generation attempt."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.services import shot_video_service
from app.services.business_events import task_events
from app.services.canonical_execution_invalidation import CanonicalExecutionConflict
from app.services.clip_result_recovery import accept_cancelled_generate_receipt
from app.services.continuous_clip_av import continuous_assembly_spans
from app.services.task_service import TaskService


@pytest.fixture
def cancelled_receipt(db_session, tmp_path, monkeypatch):
    novel = Novel(id="accepted-novel", title="Acceptance")
    chapter = Chapter(id="accepted-chapter", novel_id=novel.id, number=1, title="Chapter")
    graph = {
        "132": {"class_type": "PrimitiveFloat", "inputs": {"value": 15.0}},
        "138": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "duration: 15s"}},
        "169": {"class_type": "SaveVideo", "inputs": {}},
    }
    workflow = Workflow(id="accepted-workflow", name="Frozen", type="multi_reference_video",
                        workflow_json=json.dumps(graph),
                        node_mapping=json.dumps({"duration_seconds_node_id": "132", "video_save_node_id": "169"}),
                        extension=json.dumps({"max_clip_duration": 20}))
    shot = Shot(id="accepted-shot", chapter_id=chapter.id, index=6, video_status="failed",
                video_director_plan=json.dumps({"canonical_visual_plan": True, "clip_plan_revision": 1,
                    "task_error_message": "任务已取消", "error_message": "任务已取消",
                    "clip_plan": [
                        {"clip_index": 1, "clip_plan_revision": 1, "capability": "GENERATE",
                         "planned_duration": 13.7, "execution_status": "FAILED", "error_message": "old failure"},
                        {"clip_index": 2, "clip_plan_revision": 1, "capability": "EXTEND",
                         "previous_clip_index": 1, "planned_duration": 8.2, "execution_status": "PLANNED"},
                    ]}))
    contract = {"capability": "GENERATE", "artifact_kind": "CLIP_ONLY",
                "clip": {"clip_id": f"{shot.id}:clip:1", "clip_index": 1, "clip_plan_revision": 1,
                         "duration_seconds": 13.7}}
    optimizer = {"status": "OPTIMIZED", "optimized_prompt": "duration: 15s",
                 "authority_check": {"passed": True},
                 "output": {"av_timeline": {"optimized_duration": 15.0}}}
    metadata = {"execution_scope": "CLIP", "clip_id": f"{shot.id}:clip:1", "clip_index": 1,
                "clip_plan_revision": 1, "capability": "GENERATE", "artifact_kind": "CLIP_ONLY",
                "planned_duration": 13.7, "requested_duration": 13.7,
                "execution_contract": contract, "video_save_node_id": "169",
                "h3_prompt_optimizer": optimizer, "approval_status": "GENERATING"}
    source = Task(id="cancelled-source", name="C1", type="shot_video", status="cancelled",
                  novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
                  workflow_id=workflow.id, workflow_name=workflow.name,
                  workflow_json=json.dumps(graph), prompt_text="duration: 15s",
                  comfyui_prompt_id="completed-prompt", metadata_json=json.dumps(metadata),
                  error_message="任务被用户取消",
                  created_at=datetime.utcnow() - timedelta(minutes=10))
    batch = Task(id="paused-batch", name="batch", type="shot_video_batch", status="paused",
                 novel_id=novel.id, chapter_id=chapter.id)
    db_session.add_all([novel, chapter, workflow, shot, source, batch])
    db_session.commit()
    history = {"prompt": [0, "completed-prompt", graph],
               "status": {"status_str": "success", "completed": True},
               "outputs": {"169": {"videos": [{"filename": "c1.mp4", "type": "output"}]}}}
    video = tmp_path / "c1.mp4"
    video.write_bytes(b"test video bytes")
    monkeypatch.setattr(shot_video_service.file_storage, "download_video", AsyncMock(return_value=str(video)))
    monkeypatch.setattr(shot_video_service.file_storage, "download_video_receipt", AsyncMock(return_value=str(video)))
    media = {"video_duration": 15.083333333333334, "frame_count": 362, "fps": 24,
             "timebase": "1/24", "has_audio": True, "audio_duration": 15.08,
             "audio_start_time": 0, "width": 864, "height": 480, "sha256": "test-sha"}
    monkeypatch.setattr("app.services.continuous_clip_av.probe_clip_av", lambda _: media)
    service = TaskService(db_session)
    service.comfyui_service.client.get_prompt_state = AsyncMock(return_value={"state": "completed", "history": history})
    service.comfyui_service.client.queue_prompt = AsyncMock(side_effect=AssertionError("must not generate"))
    return source, shot, batch, service, history, media


@pytest.mark.asyncio
async def test_accept_137_planned_150_optimized_15083_actual(cancelled_receipt, db_session):
    source, shot, batch, service, _, media = cancelled_receipt
    accepted = await accept_cancelled_generate_receipt(
        source, "completed-prompt", 1, db_session, service.comfyui_service,
    )
    db_session.refresh(source)
    db_session.refresh(shot)
    db_session.refresh(batch)
    meta = json.loads(accepted.metadata_json)
    clips = json.loads(shot.video_director_plan)["clip_plan"]
    assert source.status == "cancelled" and source.error_message == "任务被用户取消"
    assert source.result_url is None and accepted.source_task_id == source.id
    assert accepted.status == "completed" and accepted.result_url
    assert meta["planned_duration"] == 13.7 and meta["optimized_duration"] == 15.0
    assert meta["actual_duration"] == media["video_duration"]
    assert meta["duration_delta"] == pytest.approx(1.3)
    assert meta["actual_duration_delta"] == pytest.approx(media["video_duration"] - 15.0)
    assert clips[0]["execution_status"] == "APPROVED"
    assert clips[0]["generated_by_task_id"] == accepted.id
    assert clips[0]["planned_duration"] == 13.7
    assert clips[0]["optimized_duration"] == 15.0
    assert clips[0]["actual_duration"] == media["video_duration"]
    assert clips[1]["execution_status"] == "PLANNED"
    assert shot.video_status == "pending" and shot.video_url is None
    assert "task_error_message" not in json.loads(shot.video_director_plan)
    assert batch.status == "paused"
    assert task_events(accepted)[0][0] == "clip.result.recovery.completed"
    assert task_events(accepted)[0][1]["details"]["actual_duration"] == media["video_duration"]
    service.comfyui_service.client.queue_prompt.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_optimized_duration_is_rejected_before_receipt(cancelled_receipt, db_session):
    source, _, _, service, _, _ = cancelled_receipt
    metadata = json.loads(source.metadata_json)
    metadata["h3_prompt_optimizer"]["output"]["av_timeline"]["optimized_duration"] = 21.0
    source.metadata_json = json.dumps(metadata)
    db_session.commit()
    with pytest.raises(ValueError, match="workflow capability"):
        await accept_cancelled_generate_receipt(source, "completed-prompt", 1, db_session, service.comfyui_service)
    service.comfyui_service.client.get_prompt_state.assert_not_awaited()
    assert db_session.query(Task).filter(Task.source_task_id == source.id).count() == 0


@pytest.mark.asyncio
async def test_changed_receipt_is_rejected_without_mutation(cancelled_receipt, db_session):
    source, shot, _, service, history, _ = cancelled_receipt
    history["prompt"][2] = {"other": {}}
    with pytest.raises(CanonicalExecutionConflict, match="RECEIPT_MISMATCH"):
        await accept_cancelled_generate_receipt(source, "completed-prompt", 1, db_session, service.comfyui_service)
    assert db_session.query(Task).filter(Task.source_task_id == source.id).count() == 0
    assert json.loads(shot.video_director_plan)["clip_plan"][0]["execution_status"] == "FAILED"


@pytest.mark.asyncio
async def test_invalid_media_does_not_promote_cancelled_result(cancelled_receipt, db_session, monkeypatch):
    source, shot, batch, service, _, _ = cancelled_receipt
    def invalid(_):
        raise ValueError("CLIP_AV_UNREADABLE")
    monkeypatch.setattr("app.services.continuous_clip_av.probe_clip_av", invalid)
    with pytest.raises(ValueError, match="CLIP_AV_UNREADABLE"):
        await accept_cancelled_generate_receipt(
            source, "completed-prompt", 1, db_session, service.comfyui_service,
        )
    db_session.refresh(source)
    db_session.refresh(shot)
    db_session.refresh(batch)
    recovered = db_session.query(Task).filter(Task.source_task_id == source.id).one()
    assert source.status == "cancelled" and recovered.status == "failed"
    assert task_events(recovered)[0][0] == "clip.result.recovery.failed"
    assert shot.video_status == "failed"
    assert json.loads(shot.video_director_plan)["clip_plan"][0]["execution_status"] == "FAILED"
    assert batch.status == "paused"


@pytest.mark.asyncio
async def test_acceptance_is_idempotent_after_success(cancelled_receipt, db_session):
    source, _, _, service, _, _ = cancelled_receipt
    first = await accept_cancelled_generate_receipt(
        source, "completed-prompt", 1, db_session, service.comfyui_service,
    )
    second = await accept_cancelled_generate_receipt(
        source, "completed-prompt", 1, db_session, service.comfyui_service,
    )
    assert first.id == second.id
    assert db_session.query(Task).filter(Task.source_task_id == source.id).count() == 1
    service.comfyui_service.client.get_prompt_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_restart_uses_prior_failed_download_receipt(cancelled_receipt, db_session):
    source, _, _, service, history, _ = cancelled_receipt
    metadata = json.loads(source.metadata_json)
    metadata.update(manual_receipt_recovery=True, comfyui_history=history)
    prior = Task(id="prior-failed-download", name="prior", type="shot_video", status="failed",
                 source_task_id=source.id, novel_id=source.novel_id, chapter_id=source.chapter_id,
                 shot_id=source.shot_id, workflow_id=source.workflow_id,
                 workflow_json=source.workflow_json, comfyui_prompt_id=source.comfyui_prompt_id,
                 metadata_json=json.dumps(metadata), error_message="下载视频失败",
                 created_at=datetime.utcnow() - timedelta(minutes=1))
    db_session.add(prior)
    db_session.commit()
    service.comfyui_service.client.get_prompt_state = AsyncMock(return_value={"state": "missing"})
    accepted = await accept_cancelled_generate_receipt(
        source, "completed-prompt", 1, db_session, service.comfyui_service,
    )
    assert accepted.status == "completed"
    assert json.loads(accepted.metadata_json)["receipt_source"] == "PRIOR_VALIDATED_BUSINESS_TASK"
    assert prior.status == "failed"


@pytest.mark.asyncio
async def test_restart_rejects_unverified_prior_receipt(cancelled_receipt, db_session):
    source, _, _, service, history, _ = cancelled_receipt
    metadata = json.loads(source.metadata_json)
    metadata.update(manual_receipt_recovery=True, comfyui_history={**history, "prompt": [0, "wrong", {}]})
    prior = Task(id="prior-bad-receipt", name="prior", type="shot_video", status="failed",
                 source_task_id=source.id, novel_id=source.novel_id, chapter_id=source.chapter_id,
                 shot_id=source.shot_id, workflow_id=source.workflow_id,
                 workflow_json=source.workflow_json, comfyui_prompt_id=source.comfyui_prompt_id,
                 metadata_json=json.dumps(metadata), error_message="下载视频失败",
                 created_at=datetime.utcnow() - timedelta(minutes=1))
    db_session.add(prior)
    db_session.commit()
    service.comfyui_service.client.get_prompt_state = AsyncMock(return_value={"state": "missing"})
    with pytest.raises(CanonicalExecutionConflict, match="RECEIPT_MISMATCH"):
        await accept_cancelled_generate_receipt(source, "completed-prompt", 1, db_session, service.comfyui_service)
    assert db_session.query(Task).filter(Task.source_task_id == source.id).count() == 1


@pytest.mark.asyncio
async def test_ordinary_reconciler_does_not_race_explicit_acceptance(cancelled_receipt, db_session):
    source, _, _, service, _, _ = cancelled_receipt
    metadata = json.loads(source.metadata_json)
    metadata["manual_receipt_recovery"] = True
    source.metadata_json = json.dumps(metadata)
    source.status = "running"
    db_session.commit()
    service.comfyui_service.get_queue_info = AsyncMock(return_value={"queue_running": [], "queue_pending": []})
    assert await service.reconcile_active_tasks([source]) == 0
    assert source.status == "running"
    service.comfyui_service.client.get_prompt_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_c2_previous_uses_accepted_c1_physical_end(cancelled_receipt, db_session, monkeypatch, tmp_path):
    from app.services.shot_video_service import resolve_extend_previous_av

    source, shot, _, service, _, media = cancelled_receipt
    accepted = await accept_cancelled_generate_receipt(
        source, "completed-prompt", 1, db_session, service.comfyui_service,
    )
    local = tmp_path / "approved-c1.mp4"
    local.write_bytes(b"video")
    monkeypatch.setattr("app.services.shot_video_service.url_to_local_path", lambda _: str(local))
    monkeypatch.setattr("app.services.shot_video_service.probe_clip_av", lambda _: media)
    previous = resolve_extend_previous_av(
        db_session, accepted.novel_id, accepted.chapter_id, shot,
        {"previous_clip_index": 1, "clip_plan_revision": 1},
        {"clip_index": 1, "clip_plan_revision": 1,
         "generated_by_task_id": accepted.id, "result_url": accepted.result_url,
         "source_frame_start": 0},
    )
    assert previous["generated_by_task_id"] == accepted.id
    assert previous["physical_output"]["frame_count"] == 362
    assert previous["physical_output"]["video_duration"] == media["video_duration"]
    assert previous["local_path"] == str(local)


def test_assembly_uses_physical_frames_instead_of_planned_duration():
    first = {"task_id": "c1", "path": "c1.mp4", "capability": "GENERATE",
             "physical_output": {"frame_count": 362, "fps": 24, "timebase": "1/24",
                                 "video_duration": 362 / 24, "planned_duration": 13.7}}
    second = {"task_id": "c2", "path": "c2.mp4", "capability": "EXTEND",
              "physical_output": {"frame_count": 500, "fps": 24, "timebase": "1/24",
                                  "physical_output_role": "NATIVE_CONTINUITY_OUTPUT",
                                  "has_audio": True, "overlap_frames": 39,
                                  "overlap_duration": 39 / 24,
                                  "previous": {"generated_by_task_id": "c1", "source_frame_start": 0,
                                               "physical_output": {"frame_count": 362, "fps": 24,
                                                                   "timebase": "1/24"}}}}
    projection = continuous_assembly_spans([first, second])
    assert projection["frame_count"] == 500
    assert projection["duration"] == 500 / 24
    assert projection["boundaries"][0]["global_overlap_start"] == 362 - 39
