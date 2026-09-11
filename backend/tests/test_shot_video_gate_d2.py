import asyncio
import json

import pytest
from fastapi import HTTPException

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.api.shots import BatchShotVideoRequest, generate_shot_videos_batch, resume_active_shot_video_batches
from app.repositories import ChapterRepository, NovelRepository, ShotRepository
from app.repositories.task import TaskRepository
from app.services.shot_video_service import generate_shot_video_task
from app.services.task_service import TaskService


def test_disjoint_video_batches_queue_instead_of_reusing_active_batch(db_session):
    novel = Novel(title="Batch queue")
    db_session.add(novel)
    db_session.commit()
    db_session.refresh(novel)
    chapter = Chapter(novel_id=novel.id, number=1, title="Chapter", content="content")
    db_session.add(chapter)
    db_session.commit()
    db_session.refresh(chapter)
    shots = [
        Shot(chapter_id=chapter.id, index=index, description=f"Shot {index}", characters="[]", props="[]", duration=4)
        for index in range(1, 4)
    ]
    db_session.add_all(shots)
    db_session.commit()
    for shot in shots:
        db_session.refresh(shot)

    async def submit(shot_ids):
        return await generate_shot_videos_batch(
            novel.id,
            chapter.id,
            BatchShotVideoRequest(shot_ids=shot_ids),
            novel_repo=NovelRepository(db_session),
            chapter_repo=ChapterRepository(db_session),
            shot_repo=ShotRepository(db_session),
            db=db_session,
        )

    first = asyncio.run(submit([shots[0].id]))
    second = asyncio.run(submit([shots[1].id]))
    duplicate = asyncio.run(submit([shots[1].id]))

    assert first["data"]["taskId"] != second["data"]["taskId"]
    assert duplicate["data"]["taskId"] == second["data"]["taskId"]
    assert db_session.query(Task).filter(Task.type == "shot_video_batch").count() == 2

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(submit([shots[0].id, shots[2].id]))
    assert exc_info.value.status_code == 409


def test_service_restart_holds_batch_without_assuming_missing_cid_is_unsubmitted(db_session, monkeypatch):
    parent = Task(type="shot_video_batch", status="running", name="batch")
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)
    child = Task(
        type="shot_video",
        status="running",
        name="child",
        parent_task_id=parent.id,
        comfyui_prompt_id=None,
    )
    db_session.add(child)
    db_session.commit()
    db_session.refresh(child)
    parent_id = parent.id
    child_id = child.id
    saved = {column.key: getattr(child, column.key) for column in Task.__table__.columns}
    monkeypatch.setattr("app.api.shots.SessionLocal", lambda: db_session)

    resume_active_shot_video_batches()

    recovered_parent = db_session.query(Task).filter(Task.id == parent_id).one()
    assert recovered_parent.status == "failed"
    assert "BATCH_EXECUTION_REVIEW_REQUIRED" in recovered_parent.error_message
    recovered_child = db_session.query(Task).filter(Task.id == child_id).one()
    assert {column.key: getattr(recovered_child, column.key) for column in Task.__table__.columns} == saved


def test_service_restart_preserves_child_already_submitted_to_comfyui(db_session, monkeypatch):
    parent = Task(type="shot_video_batch", status="running", name="batch")
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)
    child = Task(
        type="shot_video",
        status="running",
        name="child",
        parent_task_id=parent.id,
        comfyui_prompt_id="prompt-1",
    )
    db_session.add(child)
    db_session.commit()
    db_session.refresh(child)
    parent_id = parent.id
    child_id = child.id
    monkeypatch.setattr("app.api.shots.SessionLocal", lambda: db_session)

    resume_active_shot_video_batches()

    assert db_session.query(Task).filter(Task.id == parent_id).one().status == "failed"
    assert db_session.query(Task).filter(Task.id == child_id).one().status == "running"


def _create_video_fixture(db_session, tmp_path, *, task_shot_id="USE_B", task_name="生成视频: 镜2"):
    novel = Novel(title="Gate D2")
    db_session.add(novel)
    db_session.commit()
    db_session.refresh(novel)

    chapter = Chapter(novel_id=novel.id, number=1, title="Chapter", content="content")
    db_session.add(chapter)
    db_session.commit()
    db_session.refresh(chapter)

    image_path = tmp_path / "shot.png"
    image_path.write_bytes(b"image")
    shot_a = Shot(
        chapter_id=chapter.id,
        index=1,
        description="Shot A",
        characters=json.dumps([], ensure_ascii=False),
        scene="",
        props=json.dumps([], ensure_ascii=False),
        duration=4,
        estimated_duration=4,
        image_url="/api/files/a.png",
        video_status="pending",
    )
    shot_b = Shot(
        chapter_id=chapter.id,
        index=2,
        description="Shot B",
        characters=json.dumps([], ensure_ascii=False),
        scene="",
        props=json.dumps([], ensure_ascii=False),
        duration=4,
        estimated_duration=4,
        image_url="/api/files/b.png",
        video_status="generating",
    )
    db_session.add_all([shot_a, shot_b])
    db_session.commit()
    db_session.refresh(shot_a)
    db_session.refresh(shot_b)

    workflow = Workflow(
        name="Video workflow",
        type="video",
        workflow_json="{}",
        node_mapping=json.dumps({"video_save_node_id": "150"}),
        is_active=True,
    )
    db_session.add(workflow)
    db_session.commit()
    db_session.refresh(workflow)

    if task_shot_id == "USE_B":
        resolved_task_shot_id = shot_b.id
    elif task_shot_id == "USE_NONE":
        resolved_task_shot_id = None
    else:
        resolved_task_shot_id = task_shot_id
    task = Task(
        type="shot_video",
        status="pending",
        name=task_name,
        description="Generate video",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=resolved_task_shot_id,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        metadata_json=json.dumps({"shot_index": 2}, ensure_ascii=False),
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return novel, chapter, shot_a, shot_b, workflow, task, image_path


def _patch_video_worker(monkeypatch, db_session, tmp_path, image_path):
    class FakeComfy:
        async def generate_shot_video_with_workflow(self, **kwargs):
            callback = kwargs.get("on_prompt_queued")
            if callback:
                callback("prompt-d2", {"workflow": True})
            return {"success": True, "video_url": "http://comfy/video.mp4", "prompt_id": "prompt-d2"}

    async def fake_prompt(**_kwargs):
        return "stable shot-id prompt"

    async def fake_download_video(**_kwargs):
        video_path = tmp_path / "generated.mp4"
        video_path.write_bytes(b"video")
        return str(video_path)

    monkeypatch.setattr("app.services.shot_video_service.SessionLocal", lambda: db_session)
    monkeypatch.setattr("app.services.shot_video_service.url_to_local_path", lambda _value: str(image_path))
    monkeypatch.setattr("app.services.shot_video_service.build_h3_video_prompt", fake_prompt)
    monkeypatch.setattr("app.services.shot_video_service.ComfyUIService", FakeComfy)
    monkeypatch.setattr("app.services.shot_video_service.file_storage.download_video", fake_download_video)


def test_shot_video_worker_uses_task_shot_id_after_reorder(db_session, tmp_path, monkeypatch):
    novel, chapter, shot_a, shot_b, workflow, task, image_path = _create_video_fixture(db_session, tmp_path)
    old_shot_index = shot_b.index
    shot_a.index = 2
    shot_b.index = 1
    db_session.commit()
    _patch_video_worker(monkeypatch, db_session, tmp_path, image_path)
    task_id = task.id
    shot_a_id = shot_a.id
    shot_b_id = shot_b.id

    asyncio.run(generate_shot_video_task(task_id, novel.id, chapter.id, shot_b_id, old_shot_index, workflow.id, shot_b.image_url))

    task = db_session.query(Task).filter(Task.id == task_id).one()
    shot_a = db_session.query(Shot).filter(Shot.id == shot_a_id).one()
    shot_b = db_session.query(Shot).filter(Shot.id == shot_b_id).one()
    assert task.status == "completed"
    assert shot_b.video_status == "completed"
    assert shot_b.video_url
    assert shot_a.video_status == "pending"
    assert not shot_a.video_url


def test_shot_video_worker_missing_shot_id_fails_without_index_fallback(db_session, tmp_path, monkeypatch):
    novel, chapter, shot_a, _shot_b, workflow, task, image_path = _create_video_fixture(db_session, tmp_path, task_shot_id="USE_NONE")
    _patch_video_worker(monkeypatch, db_session, tmp_path, image_path)
    task_id = task.id
    shot_a_id = shot_a.id

    asyncio.run(generate_shot_video_task(task_id, novel.id, chapter.id, None, shot_a.index, workflow.id, shot_a.image_url))

    task = db_session.query(Task).filter(Task.id == task_id).one()
    shot_a = db_session.query(Shot).filter(Shot.id == shot_a_id).one()
    assert task.status == "failed"
    assert "shot_id" in task.error_message
    assert shot_a.video_status == "pending"
    assert not shot_a.video_url


def test_shot_video_worker_nonexistent_shot_id_fails_without_index_fallback(db_session, tmp_path, monkeypatch):
    novel, chapter, shot_a, _shot_b, workflow, task, image_path = _create_video_fixture(db_session, tmp_path, task_shot_id="missing-shot-id")
    _patch_video_worker(monkeypatch, db_session, tmp_path, image_path)
    task_id = task.id
    shot_a_id = shot_a.id

    asyncio.run(generate_shot_video_task(task_id, novel.id, chapter.id, "missing-shot-id", shot_a.index, workflow.id, shot_a.image_url))

    task = db_session.query(Task).filter(Task.id == task_id).one()
    shot_a = db_session.query(Shot).filter(Shot.id == shot_a_id).one()
    assert task.status == "failed"
    assert task.error_message == "分镜不存在"
    assert shot_a.video_status == "pending"
    assert not shot_a.video_url


def test_shot_video_worker_prefers_shot_id_over_conflicting_old_index(db_session, tmp_path, monkeypatch):
    novel, chapter, shot_a, shot_b, workflow, task, image_path = _create_video_fixture(db_session, tmp_path)
    _patch_video_worker(monkeypatch, db_session, tmp_path, image_path)
    task_id = task.id
    shot_a_id = shot_a.id
    shot_b_id = shot_b.id

    asyncio.run(generate_shot_video_task(task_id, novel.id, chapter.id, shot_b_id, shot_a.index, workflow.id, shot_a.image_url))

    task = db_session.query(Task).filter(Task.id == task_id).one()
    shot_a = db_session.query(Shot).filter(Shot.id == shot_a_id).one()
    shot_b = db_session.query(Shot).filter(Shot.id == shot_b_id).one()
    assert task.status == "completed"
    assert shot_b.video_status == "completed"
    assert shot_b.video_url
    assert shot_a.video_status == "pending"
    assert not shot_a.video_url


def test_shot_video_retry_without_shot_id_rejects_without_rewriting_evidence(db_session, tmp_path, monkeypatch):
    _novel, _chapter, shot_a, _shot_b, _workflow, task, _image_path = _create_video_fixture(
        db_session,
        tmp_path,
        task_shot_id="USE_NONE",
        task_name="生成视频: 镜1",
    )
    task.status = "failed"
    task.error_message = "Original video failure"
    db_session.commit()
    task_id = task.id
    shot_a_id = shot_a.id
    saved = {column.key: getattr(task, column.key) for column in Task.__table__.columns}

    class FakeComfy:
        pass

    monkeypatch.setattr("app.services.task_service.ComfyUIService", FakeComfy)

    result = TaskService(db_session).retry_task(task_id, db_session)

    task = db_session.query(Task).filter(Task.id == task_id).one()
    shot_a = db_session.query(Shot).filter(Shot.id == shot_a_id).one()
    assert result["success"] is False
    assert result["status_code"] == 400
    assert task.status == "failed"
    assert {column.key: getattr(task, column.key) for column in Task.__table__.columns} == saved
    assert shot_a.video_status == "pending"


def test_active_shot_video_lookup_does_not_fallback_by_name_when_shot_id_supplied(db_session, tmp_path):
    novel, chapter, shot_a, shot_b, _workflow, task, _image_path = _create_video_fixture(db_session, tmp_path)
    task.shot_id = shot_a.id
    task.name = "生成视频: 镜2"
    task.status = "running"
    db_session.commit()

    found = TaskRepository(db_session).get_active_shot_task(
        novel.id,
        chapter.id,
        shot_b.index,
        "shot_video",
        shot_id=shot_b.id,
    )

    assert found is None


def _request_shot_video_regeneration(db_session, monkeypatch, novel, chapter, shot, *, preflight=None, skip_llm=True):
    from unittest.mock import Mock
    from app.api.shots import GenerateVideoRequest, generate_shot_video
    from app.repositories import WorkflowRepository

    enqueue = Mock()
    monkeypatch.setattr("app.api.shots.generate_shot_video_task", enqueue)
    monkeypatch.setattr(TaskService, "validate_workflow_node_mapping", Mock(return_value=(True, "")))
    monkeypatch.setattr("app.api.shots._assert_audio_drive_ready_for_video", preflight or Mock())

    result = asyncio.run(generate_shot_video(
        novel.id, chapter.id, shot.id,
        GenerateVideoRequest(skip_llm_when_prompt_exists=skip_llm),
        novel_repo=NovelRepository(db_session),
        chapter_repo=ChapterRepository(db_session),
        task_repo=TaskRepository(db_session),
        workflow_repo=WorkflowRepository(db_session),
        shot_repo=ShotRepository(db_session),
    ))

    task_id = result["data"]["taskId"]
    task = db_session.query(Task).filter(Task.id == task_id).one()
    db_session.refresh(shot)
    assert result["success"] is True
    assert result["data"]["status"] == task.status == "pending"
    assert task.shot_id == shot.id
    assert shot.video_task_id == task_id
    assert shot.video_status == "generating"
    enqueue.assert_called_once_with(
        task_id, novel.id, chapter.id, shot.id, shot.index, task.workflow_id, shot.image_url,
        use_keyframes=True, use_reference_audio=True, selected_mode="SINGLE_FRAME",
        skip_llm_when_prompt_exists=skip_llm,
    )
    return task_id


@pytest.mark.parametrize("evidence", ["upload", "queue", "video", "historical-graph"])
@pytest.mark.parametrize("skip_llm", [False, True])
def test_generate_shot_video_preserves_failed_h3_fallback_evidence(db_session, tmp_path, monkeypatch, evidence, skip_llm):
    from app.services.shot_video_service import _save_h3_prompt_gate
    from app.services.video_director_ai import (
        _build_deterministic_h3_prompt, _has_recorded_h3_fallback, prepare_h3_prompt,
    )

    novel, chapter, _shot_a, shot, _workflow, task, _image = _create_video_fixture(db_session, tmp_path)
    clip = {"clip_index": 1, "start_time": 0, "end_time": 4}
    candidate = _build_deterministic_h3_prompt(shot, "SINGLE_FRAME", clip, [], [], [], {})
    if evidence == "historical-graph":
        task.prompt_text = candidate
        task.comfyui_prompt_id = "prior-h3-prompt"
        task.workflow_json = json.dumps({
            "text": {"class_type": "CR Prompt Text", "inputs": {"prompt": candidate}},
            "h3": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"prompt": ["text", 0]}},
        })
    else:
        prepared = prepare_h3_prompt(
            candidate, constraint="", continuity_lock="", subject_manifest={}, speaker_timeline=[],
            audio_drive_enabled=False,
            fallback_context={"shot_index": shot.index, "selected_mode": "SINGLE_FRAME", **clip},
        )
        record = {
            **prepared, "attempt_id": "prior-attempt", "clip_index": 1, "origin": "fallback",
            "target": {"id": task.id}, "submission_state": "prepared",
        }
        if evidence != "upload":
            record["prequeue_validation"] = {"passed": True}
        _save_h3_prompt_gate(
            db_session, task, record, error=f"{evidence} failed",
            prompt_id="prior-h3-prompt" if evidence == "video" else None,
        )
    task.status = "failed"
    task.error_message = f"{evidence} failed"
    shot.video_status = "failed"
    shot.video_task_id = task.id
    shot.video_director_plan = json.dumps({
        "selected_mode": "SINGLE_FRAME", "clips": [{**clip, "prompt_text": candidate}],
    })
    db_session.commit()
    prior_id = task.id
    saved = {field: getattr(task, field) for field in (
        "metadata_json", "workflow_json", "prompt_text", "comfyui_prompt_id", "status", "error_message",
    )}
    assert _has_recorded_h3_fallback(db_session, shot, clip, candidate, {}) is True

    def preflight(*_args, db=None):
        assert db is db_session
        db_session.refresh(shot)
        assert shot.video_task_id == prior_id
        assert db_session.query(Task).filter(Task.id == prior_id).one().status == "failed"

    new_id = _request_shot_video_regeneration(
        db_session, monkeypatch, novel, chapter, shot, preflight=preflight, skip_llm=skip_llm,
    )

    assert new_id != prior_id
    prior = db_session.query(Task).filter(Task.id == prior_id).one()
    assert {field: getattr(prior, field) for field in saved} == saved
    proof = {"target": {"id": new_id}}
    assert _has_recorded_h3_fallback(db_session, shot, clip, candidate, proof) is True
    assert proof["fallback_source_task_id"] == prior_id
    assert _has_recorded_h3_fallback(db_session, shot, clip, "invalid replacement prompt", {}) is False


@pytest.mark.parametrize("metadata,graph_class,retained", [
    pytest.param(None, "LTXVConditioning", False, id="non-h3-raw-prompt-only"),
    pytest.param("{broken", "LTXVConditioning", True, id="malformed-metadata-retained-without-purpose-proof"),
    pytest.param('{"h3_prompt_gate": {"version": 2}}', "LTXVConditioning", False, id="wrong-gate-version"),
    pytest.param('{"h3_prompt_gate": {"version": 1}}', "LTXVConditioning", True, id="gate-marker-only"),
    pytest.param(None, "MiniMaxH3ReferenceToVideo", True, id="unsubmitted-h3-graph"),
])
def test_generate_shot_video_retention_does_not_grant_fallback_proof(db_session, tmp_path, monkeypatch, metadata, graph_class, retained):
    from app.services.video_director_ai import _build_deterministic_h3_prompt, _has_recorded_h3_fallback

    novel, chapter, _shot_a, shot, workflow, task, _image = _create_video_fixture(db_session, tmp_path)
    clip = {"clip_index": 1, "start_time": 0, "end_time": 4}
    candidate = _build_deterministic_h3_prompt(shot, "SINGLE_FRAME", clip, [], [], [], {})
    task.status = "failed"
    task.metadata_json = metadata
    task.prompt_text = candidate
    task.workflow_json = json.dumps({"h3": {"class_type": graph_class, "inputs": {"prompt": candidate}}})
    task.workflow_name = workflow.name = "MiniMaxH3ReferenceToVideo"
    shot.video_status = "failed"
    shot.video_task_id = task.id
    shot.video_director_plan = json.dumps({
        "selected_mode": "SINGLE_FRAME", "clips": [{**clip, "prompt_text": candidate}],
        "ai_calls": [{"step": "11", "status": "success", "final_prompt": candidate,
                      "parsed_result": {"fallback": "deterministic_prompt"}}],
    })
    db_session.commit()
    prior_id = task.id
    assert _has_recorded_h3_fallback(db_session, shot, clip, candidate, {}) is False

    new_id = _request_shot_video_regeneration(db_session, monkeypatch, novel, chapter, shot)

    assert new_id != prior_id
    assert (db_session.query(Task).filter(Task.id == prior_id).first() is not None) is retained
    assert db_session.query(Task).filter(Task.shot_id == shot.id).count() == (2 if retained else 1)
    proof = {"target": {"id": new_id}}
    assert _has_recorded_h3_fallback(db_session, shot, clip, candidate, proof) is False
    assert "fallback_source_task_id" not in proof
