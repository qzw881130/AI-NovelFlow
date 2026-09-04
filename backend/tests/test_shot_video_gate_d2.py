import asyncio
import json

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories.task import TaskRepository
from app.services.shot_video_service import generate_shot_video_task
from app.services.task_service import TaskService


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


def test_shot_video_retry_requires_existing_task_shot_id(db_session, tmp_path, monkeypatch):
    _novel, _chapter, shot_a, _shot_b, _workflow, task, _image_path = _create_video_fixture(
        db_session,
        tmp_path,
        task_shot_id="USE_NONE",
        task_name="生成视频: 镜1",
    )
    task.status = "failed"
    db_session.commit()
    task_id = task.id
    shot_a_id = shot_a.id

    class FakeComfy:
        pass

    monkeypatch.setattr("app.services.task_service.ComfyUIService", FakeComfy)

    result = TaskService(db_session).retry_task(task_id, db_session)

    task = db_session.query(Task).filter(Task.id == task_id).one()
    shot_a = db_session.query(Shot).filter(Shot.id == shot_a_id).one()
    assert result["success"] is False
    assert task.status == "failed"
    assert "shot_id" in task.error_message
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
