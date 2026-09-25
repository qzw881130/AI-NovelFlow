import json
from pathlib import Path
from unittest.mock import patch

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.services.task_service import TaskService


def test_retry_semantic_clip_preserves_revision_dialogue_dependency_duration_and_shot_url(db_session, tmp_path):
    novel = Novel(id="novel-1", title="Test")
    chapter = Chapter(id="chapter-1", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(
        id="shot-1", chapter_id=chapter.id, index=4, duration=28,
        image_url="/api/files/shot-image.png", video_url="/api/files/assembled-shot.mp4",
        video_status="completed",
        video_director_plan=json.dumps({
            "clip_plan_revision": 4,
            "clip_plan": [
                {"clip_index": 1, "start_time": 0, "end_time": 14, "planned_duration": 14},
                {"clip_index": 2, "start_time": 14, "end_time": 28, "planned_duration": 14},
            ],
        }),
    )
    previous_video = tmp_path / "c1.mp4"
    previous_video.write_bytes(b"approved c1")
    previous_url = "/api/files/c1.mp4"
    previous = Task(
        id="c1-task", type="shot_video", status="completed", novel_id=novel.id,
        chapter_id=chapter.id, shot_id=shot.id, name="C1", result_url=previous_url,
        metadata_json=json.dumps({
            "execution_scope": "CLIP", "clip_id": "shot-1:clip:1", "clip_index": 1,
            "clip_plan_revision": 4, "capability": "SINGLE_FRAME", "approval_status": "APPROVED",
        }),
    )
    dialogue_assignment = [{"dialogue_id": "D7", "text": "exact C2 segment"}]
    clip_metadata = {
        "execution_scope": "CLIP", "clip_id": "shot-1:clip:2", "clip_index": 2,
        "clip_plan_revision": 4, "capability": "VIDEO_CONTINUATION",
        "planned_duration": 14.0, "requested_duration": 14.0,
        "dialogue_assignment": dialogue_assignment,
        "previous_approved_task_id": previous.id,
        "previous_approved_video_url": previous_url,
        "approval_mode": "AUTO_APPROVE", "approval_status": "GENERATING",
        "temporal_anchor_ids": [], "prompt_text": "old attempt prompt",
    }
    task = Task(
        id="c2-task", type="shot_video", status="failed", novel_id=novel.id,
        chapter_id=chapter.id, shot_id=shot.id, name="C2", workflow_id="continuation-workflow",
        metadata_json=json.dumps(clip_metadata), workflow_json='{"old": true}',
        comfyui_prompt_id="old-prompt-id", seed=123, result_url="/api/files/failed.mp4",
        error_message="old failure", progress=30,
    )
    db_session.add_all([novel, chapter, shot, previous, task, Workflow(
        id="continuation-workflow", name="Continuation", type="VIDEO_CONTINUATION",
        workflow_json="{}", is_active=True,
    )])
    db_session.commit()

    captured = {}
    def enqueue(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    with patch("app.services.shot_video_service.enqueue_shot_video_task", side_effect=enqueue), \
         patch("app.services.task_service.url_to_local_path", return_value=str(previous_video)):
        result = TaskService(db_session).retry_task(task.id)

    db_session.refresh(task)
    db_session.refresh(shot)
    retried = json.loads(task.metadata_json)
    assert result["success"] is True
    assert {key: retried[key] for key in (
        "execution_scope", "clip_id", "clip_index", "clip_plan_revision", "capability",
        "planned_duration", "requested_duration", "dialogue_assignment",
        "previous_approved_task_id", "previous_approved_video_url",
    )} == {key: clip_metadata[key] for key in (
        "execution_scope", "clip_id", "clip_index", "clip_plan_revision", "capability",
        "planned_duration", "requested_duration", "dialogue_assignment",
        "previous_approved_task_id", "previous_approved_video_url",
    )}
    assert task.novel_id == novel.id and task.chapter_id == chapter.id and task.shot_id == shot.id
    assert task.status == "pending"
    assert task.error_message is None and task.comfyui_prompt_id is None
    assert task.workflow_json is None and task.seed is None and task.result_url is None
    assert retried["prompt_text"] == "" and "actual_duration" not in retried
    assert shot.image_url == "/api/files/shot-image.png"
    assert shot.video_url == "/api/files/assembled-shot.mp4"
    assert shot.video_status == "completed"
    assert captured["args"][:6] == (
        task.id, novel.id, chapter.id, shot.index, task.workflow_id, shot.image_url,
    )
    assert captured["kwargs"]["selected_mode"] == "SINGLE_FRAME"
    assert captured["kwargs"]["clip_metadata"] == retried
    assert "plan_clips" not in captured["kwargs"]
    assert captured["kwargs"]["clip_metadata"]["clip_index"] == 2


def test_retry_non_clip_shot_video_keeps_legacy_shot_level_behavior(db_session):
    novel = Novel(id="novel-2", title="Test")
    chapter = Chapter(id="chapter-2", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(
        id="shot-2", chapter_id=chapter.id, index=1, image_url="/api/files/image.png",
        video_url="/api/files/old-shot.mp4",
        video_director_plan=json.dumps({"selected_mode": "MULTI_KEYFRAME"}),
    )
    task = Task(
        id="shot-task", type="shot_video", status="failed", novel_id=novel.id,
        chapter_id=chapter.id, shot_id=shot.id, name="Shot task", workflow_id="workflow",
        metadata_json=json.dumps({"legacy": "metadata"}), workflow_json='{}', seed=9,
    )
    db_session.add_all([novel, chapter, shot, task])
    db_session.commit()

    captured = {}
    def enqueue(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    with patch("app.services.shot_video_service.enqueue_shot_video_task", side_effect=enqueue):
        result = TaskService(db_session).retry_task(task.id)

    db_session.refresh(task)
    db_session.refresh(shot)
    assert result["success"] is True
    assert task.status == "pending" and task.workflow_json is None and task.seed is None
    assert shot.video_url is None and shot.video_status == "generating"
    assert captured["kwargs"].get("clip_metadata") is None
    assert captured["kwargs"]["selected_mode"] == "MULTI_KEYFRAME"


def test_clip_retry_fails_closed_when_previous_approved_dependency_is_invalid(db_session):
    novel = Novel(id="novel-3", title="Test")
    chapter = Chapter(id="chapter-3", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(
        id="shot-3", chapter_id=chapter.id, index=1,
        video_director_plan=json.dumps({"clip_plan_revision": 4, "clip_plan": [{"clip_index": 2}]}),
    )
    task = Task(
        id="c2-invalid", type="shot_video", status="failed", novel_id=novel.id,
        chapter_id=chapter.id, shot_id=shot.id, name="C2", workflow_id="continuation-workflow",
        metadata_json=json.dumps({
            "execution_scope": "CLIP", "clip_id": "shot-3:clip:2", "clip_index": 2,
            "clip_plan_revision": 4, "capability": "VIDEO_CONTINUATION",
            "planned_duration": 14, "requested_duration": 14, "dialogue_assignment": [],
            "previous_approved_task_id": "missing", "previous_approved_video_url": "/api/files/missing.mp4",
        }),
    )
    db_session.add_all([novel, chapter, shot, task, Workflow(
        id="continuation-workflow", name="Continuation", type="VIDEO_CONTINUATION",
        workflow_json="{}", is_active=True,
    )])
    db_session.commit()

    with patch("app.services.shot_video_service.enqueue_shot_video_task") as enqueue:
        result = TaskService(db_session).retry_task(task.id)

    assert result["success"] is False and result["status_code"] == 400
    enqueue.assert_not_called()
