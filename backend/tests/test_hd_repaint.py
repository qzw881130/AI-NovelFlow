import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.services.hd_repaint_service import clone_workflow_for_hd, enqueue_hd_repaint_task, get_hd_repaint_variants
from app.services.hd_repaint_service import run_hd_repaint_task
from app.services.comfyui.workflows import WorkflowBuilder


def _seed_hd_source(db_session, multi_clip=False):
    novel = Novel(title="高清重绘测试")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章", content="内容")
    db_session.add(chapter)
    db_session.flush()
    workflow_json = {
        "10": {"inputs": {"value": 0.4}, "class_type": "PrimitiveFloat"},
        "20": {"inputs": {"seed": 123456}, "class_type": "KSampler"},
        "30": {"inputs": {"filename_prefix": "video"}, "class_type": "SaveVideo"},
    }
    workflow = Workflow(
        name="高清测试视频工作流",
        type="video" if not multi_clip else "three_frame_video",
        is_active=True,
        workflow_json=json.dumps(workflow_json),
        node_mapping=json.dumps({"megapixels_node_id": "10", "video_save_node_id": "30"}),
    )
    db_session.add(workflow)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="分镜",
        characters="[]",
        props="[]",
        duration=8,
        video_url="/api/files/draft.mp4",
        video_status="completed",
    )
    db_session.add(shot)
    db_session.flush()
    clips = None
    if multi_clip:
        clips = json.dumps([
            {
                "window_index": index,
                "workflow_id": workflow.id,
                "workflow_type": "three_frame_video",
                "workflow_name": workflow.name,
                "workflow_json": workflow_json,
                "seed": 123456 + index,
                "status": "SUCCEEDED",
            }
            for index in (1, 2)
        ])
    source = Task(
        type="shot_video",
        status="completed",
        name="初稿视频",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        workflow_id=workflow.id,
        workflow_json=json.dumps(workflow_json),
        video_director_clips=clips,
        result_url=shot.video_url,
        seed=123456,
        metadata_json=json.dumps({"megapixels_node_id": "10", "video_save_node_id": "30"}),
    )
    db_session.add(source)
    db_session.flush()
    shot.video_task_id = source.id
    db_session.commit()
    return novel, chapter, shot, source


def test_clone_workflow_for_hd_changes_only_megapixels():
    source = {
        "10": {"inputs": {"value": 0.4, "other": "same"}},
        "20": {"inputs": {"seed": 98765}},
    }

    replay = clone_workflow_for_hd(source, "10", 1.0)

    assert source["10"]["inputs"]["value"] == 0.4
    assert replay["10"]["inputs"]["value"] == 1.0
    assert replay["10"]["inputs"]["other"] == "same"
    assert replay["20"] == source["20"]


@patch("app.api.hd_repaint.enqueue_hd_repaint_task")
def test_create_hd_repaint_freezes_source_without_overwriting_draft(mock_enqueue, client, db_session):
    novel, chapter, shot, source = _seed_hd_source(db_session)

    response = client.post(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/hd-repaint",
        json={"target_megapixels": 1.0},
    )

    assert response.status_code == 200
    task = db_session.query(Task).filter(Task.id == response.json()["data"]["taskId"]).one()
    metadata = json.loads(task.metadata_json)
    db_session.refresh(shot)
    assert task.type == "shot_video_hd"
    assert task.source_task_id == source.id
    assert metadata["source_workflow_json"]["10"]["inputs"]["value"] == 0.4
    assert metadata["target_megapixels"] == 1.0
    assert shot.video_url == "/api/files/draft.mp4"
    assert shot.hd_video_status == "pending"
    mock_enqueue.assert_called_once_with(task.id)


@patch("app.api.hd_repaint.enqueue_hd_repaint_batch")
@patch("app.api.hd_repaint.enqueue_hd_repaint_task")
def test_batch_hd_repaint_persists_multi_clip_children(mock_enqueue_task, mock_enqueue_batch, client, db_session):
    novel, chapter, shot, source = _seed_hd_source(db_session, multi_clip=True)

    response = client.post(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/hd-repaints/batch",
        json={"shot_ids": [shot.id], "target_megapixels": 1.2},
    )

    assert response.status_code == 200
    child = db_session.query(Task).filter(Task.type == "shot_video_hd", Task.shot_id == shot.id).one()
    clips = json.loads(child.video_director_clips)
    assert child.source_task_id == source.id
    assert child.parent_task_id == response.json()["data"]["batchTaskId"]
    assert len(clips) == 2
    assert all(clip["target_megapixels"] == 1.2 for clip in clips)
    assert all(clip["source_workflow_json"]["10"]["inputs"]["value"] == 0.4 for clip in clips)


def test_single_and_batch_children_share_the_same_serial_worker(monkeypatch):
    queued_workers = []

    class FakeWorker:
        def enqueue(self, job):
            queued_workers.append("shot_video_hd")

    monkeypatch.setattr("app.services.hd_repaint_service.worker_manager.worker", lambda name: FakeWorker() if name == "shot_video_hd" else None)
    monkeypatch.setattr("app.services.hd_repaint_service._active_hd_tasks", set())

    enqueue_hd_repaint_task("single-task")
    enqueue_hd_repaint_task("batch-child-1")
    enqueue_hd_repaint_task("batch-child-2")

    assert queued_workers == ["shot_video_hd", "shot_video_hd", "shot_video_hd"]


def test_hd_variants_keep_multiple_targets_and_execution_history(db_session):
    novel, chapter, shot, source = _seed_hd_source(db_session)
    executions = [
        Task(type="shot_video_hd", status="completed", name="1.0 A", shot_id=shot.id, source_task_id=source.id, result_url="/api/files/1a.mp4", completed_at=datetime.utcnow() - timedelta(minutes=1), metadata_json='{"target_megapixels":1.0}'),
        Task(type="shot_video_hd", status="completed", name="1.0 B", shot_id=shot.id, source_task_id=source.id, result_url="/api/files/1b.mp4", completed_at=datetime.utcnow(), metadata_json='{"target_megapixels":1.0}'),
        Task(type="shot_video_hd", status="failed", name="1.0 failed", shot_id=shot.id, source_task_id=source.id, error_message="failed", metadata_json='{"target_megapixels":1.0}'),
        Task(type="shot_video_hd", status="completed", name="1.5", shot_id=shot.id, source_task_id=source.id, result_url="/api/files/15.mp4", metadata_json='{"target_megapixels":1.5}'),
    ]
    db_session.add_all(executions)
    db_session.commit()

    variants = get_hd_repaint_variants(db_session, shot.id)

    assert [item["targetMegapixels"] for item in variants] == [1.0, 1.5]
    one_mp = variants[0]
    assert one_mp["videoUrl"] == "/api/files/1b.mp4"
    assert len(one_mp["executions"]) == 3
    assert variants[1]["videoUrl"] == "/api/files/15.mp4"


def test_shot_response_does_not_expose_current_video_variant(db_session):
    novel, chapter, shot, source = _seed_hd_source(db_session)
    db_session.add(Task(
        type="shot_video_hd",
        status="completed",
        name="1.0",
        shot_id=shot.id,
        source_task_id=source.id,
        result_url="/api/files/hd.mp4",
        metadata_json='{"target_megapixels":1.0}',
    ))
    db_session.commit()

    from app.repositories.shot_repository import ShotRepository
    response = ShotRepository(db_session).to_response(shot)

    assert "currentVideoVariant" not in response
    assert response["hdVideoVariants"][0]["targetMegapixels"] == 1.0


@patch("app.api.shots.worker_manager.worker")
def test_chapter_hd_merge_freezes_exact_target_executions(mock_worker, client, db_session):
    novel = Novel(title="目标 MP 合并")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章")
    db_session.add(chapter)
    db_session.flush()
    shots = [Shot(chapter_id=chapter.id, index=index, characters="[]", props="[]") for index in (1, 2)]
    db_session.add_all(shots)
    db_session.flush()
    executions = []
    for shot in shots:
        execution = Task(
            type="shot_video_hd",
            status="completed",
            name=f"HD {shot.index}",
            novel_id=novel.id,
            chapter_id=chapter.id,
            shot_id=shot.id,
            result_url=f"/api/files/shot-{shot.index}-1mp.mp4",
            metadata_json='{"target_megapixels":1.0}',
        )
        executions.append(execution)
    db_session.add_all(executions)
    db_session.commit()

    response = client.post(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/merge-videos",
        json={"video_variant": "hd", "target_megapixels": 1.0, "shot_ids": [shot.id for shot in shots]},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    merge_task = db_session.query(Task).filter(Task.type == "chapter_video", Task.chapter_id == chapter.id).one()
    metadata = json.loads(merge_task.metadata_json)
    assert metadata["target_megapixels"] == 1.0
    assert [item["execution_task_id"] for item in metadata["inputs"]] == [execution.id for execution in executions]

    missing = client.post(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/merge-videos",
        json={"video_variant": "hd", "target_megapixels": 1.2, "shot_ids": [shot.id for shot in shots]},
    )
    assert missing.json()["success"] is False
    assert "1.2 MP" in missing.json()["message"]


@pytest.mark.asyncio
async def test_hd_worker_replays_snapshot_and_preserves_draft(db_session, db_engine, monkeypatch, tmp_path):
    novel, chapter, shot, source = _seed_hd_source(db_session)
    from app.services.hd_repaint_service import build_hd_repaint_snapshot

    metadata, _ = build_hd_repaint_snapshot(db_session, shot, source, 1.0)
    task = Task(
        type="shot_video_hd",
        status="pending",
        name="高清重绘",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        source_task_id=source.id,
        workflow_id=source.workflow_id,
        workflow_json=json.dumps(metadata["source_workflow_json"]),
        metadata_json=json.dumps(metadata),
    )
    db_session.add(task)
    db_session.commit()
    queued = {}

    class FakeClient:
        async def queue_prompt(self, workflow):
            queued["workflow"] = workflow
            return {"success": True, "prompt_id": "hd-prompt"}

        async def wait_for_result(self, prompt_id, workflow, save_node_id, timeout=7200):
            return {"success": True, "video_url": "https://example.test/hd.mp4"}

    class FakeComfy:
        builder = WorkflowBuilder()
        client = FakeClient()

    output = tmp_path / "hd.mp4"
    output.write_bytes(b"hd-video")
    testing_session = sessionmaker(bind=db_engine)
    monkeypatch.setattr("app.services.hd_repaint_service.SessionLocal", testing_session)
    monkeypatch.setattr("app.services.hd_repaint_service.ComfyUIService", lambda: FakeComfy())
    async def fake_download(*args, **kwargs):
        return str(output)

    monkeypatch.setattr("app.services.hd_repaint_service.file_storage.download_video", fake_download)
    monkeypatch.setattr("app.services.hd_repaint_service.local_path_to_url", lambda _: "/api/files/hd.mp4")

    await run_hd_repaint_task(task.id)

    db_session.expire_all()
    refreshed_task = db_session.query(Task).filter(Task.id == task.id).one()
    refreshed_shot = db_session.query(Shot).filter(Shot.id == shot.id).one()
    assert queued["workflow"]["10"]["inputs"]["value"] == 1.0
    assert queued["workflow"]["20"]["inputs"]["seed"] == 123456
    assert refreshed_task.status == "completed"
    assert refreshed_shot.video_url == "/api/files/draft.mp4"
    assert refreshed_shot.hd_video_url == "/api/files/hd.mp4"
