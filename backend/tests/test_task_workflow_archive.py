"""Downloads from the workflow detail dialog include the submitted inputs."""

import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.models.task import Task
from app.services.file_storage import file_storage


def _read_archive(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    return ZipFile(BytesIO(response.content))


def test_task_workflow_archive_contains_json_images_and_previous_video(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    (tmp_path / "first.png").write_bytes(b"first-image")
    (tmp_path / "second.webp").write_bytes(b"second-image")
    (tmp_path / "previous.mp4").write_bytes(b"previous-video")
    workflow = {"470": {"class_type": "LoadImage", "inputs": {"image": "first.png"}}}
    task = Task(
        type="shot_video", name="续生成", status="completed",
        result_url="/api/files/previous.mp4",
        workflow_json=json.dumps(workflow),
        reference_images=json.dumps([
            {"label": "Picture 1", "url": "/api/files/first.png"},
            {"label": "Picture 2", "url": "/api/files/second.webp"},
        ]),
        metadata_json=json.dumps({"previous_approved_video_url": "/api/files/previous.mp4"}),
    )
    db_session.add(task)
    db_session.commit()

    with _read_archive(client.get(f"/api/tasks/{task.id}/workflow/archive")) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert json.loads(archive.read("workflow.json")) == workflow
        assert len(manifest["references"]) == 3
        assert [archive.read(item["archivePath"]) for item in manifest["references"]] == [
            b"first-image", b"second-image", b"previous-video",
        ]
        assert manifest["references"][2]["archivePath"].startswith("references/video/")
        assert manifest["outputs"] == []

    task.metadata_json = "{}"
    db_session.commit()
    with _read_archive(client.get(f"/api/tasks/{task.id}/workflow/archive")) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert len(manifest["references"]) == 2
        assert all(item["archivePath"].startswith("references/images/") for item in manifest["references"])


@pytest.mark.parametrize("task_type", [
    "character_portrait", "scene_image", "prop_image", "shot_image",
    "keyframe_image", "single_image_edit",
])
def test_completed_image_workflow_archive_includes_its_generated_image(
    client, db_session, monkeypatch, tmp_path, task_type,
):
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    (tmp_path / "reference.png").write_bytes(b"input-image")
    (tmp_path / "result.webp").write_bytes(b"generated-image")
    task = Task(
        type=task_type, name="生图", status="completed",
        workflow_json='{"node": {"class_type": "SaveImage"}}',
        reference_images=json.dumps([{"label": "Picture 1", "url": "/api/files/reference.png"}]),
        result_url="/api/files/result.webp",
    )
    db_session.add(task)
    db_session.commit()

    with _read_archive(client.get(f"/api/tasks/{task.id}/workflow/archive")) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert len(manifest["references"]) == 1
        assert archive.read(manifest["references"][0]["archivePath"]) == b"input-image"
        assert manifest["outputs"] == [{
            "label": "生成图片",
            "sourceUrl": "/api/files/result.webp",
            "archivePath": "outputs/generated_image.webp",
        }]
        assert archive.read("outputs/generated_image.webp") == b"generated-image"


def test_archive_reports_missing_generated_image(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    task = Task(
        type="keyframe_image", name="生图", status="completed",
        workflow_json='{"node": {}}', result_url="/api/files/missing.png",
    )
    db_session.add(task)
    db_session.commit()

    response = client.get(f"/api/tasks/{task.id}/workflow/archive")
    assert response.status_code == 409
    assert "无法打包生成图片" in response.json()["detail"]


def test_clip_archive_uses_selected_clip_references_only(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    (tmp_path / "clip-one.png").write_bytes(b"one")
    (tmp_path / "clip-two.png").write_bytes(b"two")
    (tmp_path / "clip-one.mp4").write_bytes(b"video-one")
    (tmp_path / "clip-two.mp4").write_bytes(b"video-two")
    task = Task(
        type="shot_video", shot_id="shot-1", name="多 Clip", status="completed",
        video_director_clips=json.dumps([
            {"window_index": 1, "workflow_json": {"clip": 1},
             "reference_images": [{"url": "/api/files/clip-one.png"}],
             "previous_approved_video_url": "/api/files/clip-one.mp4"},
            {"window_index": 2, "workflow_json": {"clip": 2},
             "reference_images": [{"url": "/api/files/clip-two.png"}],
             "previous_approved_video_url": "/api/files/clip-two.mp4"},
        ]),
    )
    db_session.add(task)
    db_session.commit()

    with _read_archive(client.get(f"/api/tasks/{task.id}/clips/2/workflow/archive")) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert json.loads(archive.read("workflow.json")) == {"clip": 2}
        assert manifest["windowIndex"] == 2
        assert [item["sourceUrl"] for item in manifest["references"]] == [
            "/api/files/clip-two.png", "/api/files/clip-two.mp4",
        ]
        assert [archive.read(item["archivePath"]) for item in manifest["references"]] == [b"two", b"video-two"]


def test_archive_rejects_missing_or_escaping_reference(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    task = Task(type="keyframe_image", name="缺失参考图", workflow_json='{"node": {}}')
    db_session.add(task)
    db_session.commit()

    for url in ("/api/files/missing.png", "/api/files/../outside.png"):
        task.reference_images = json.dumps([{"url": url}])
        db_session.commit()
        response = client.get(f"/api/tasks/{task.id}/workflow/archive")
        assert response.status_code == 409
        assert "无法完整打包" in response.json()["detail"]
