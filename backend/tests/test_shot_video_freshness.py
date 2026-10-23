"""The warning follows the actual main image and completed Shot video artifacts."""

import json
import os
from datetime import datetime, timedelta, timezone

from app.models.shot import Shot
from app.models.task import Task
from app.repositories.shot_repository import ShotRepository
from app.services import shot_video_freshness as freshness


def test_current_artifacts_warn_only_when_main_image_is_newer(db_session, tmp_path, monkeypatch):
    image = tmp_path / "main.png"
    video = tmp_path / "shot.mp4"
    image.write_bytes(b"image")
    video.write_bytes(b"video")
    paths = {"/api/files/main.png": str(image), "/api/files/shot.mp4": str(video)}
    monkeypatch.setattr(freshness, "url_to_local_path", paths.get)
    shot = Shot(id="freshness-shot", chapter_id="freshness-chapter", index=1,
                image_url="/api/files/main.png", video_url="/api/files/shot.mp4")
    db_session.add(shot)
    db_session.commit()

    os.utime(video, (100, 100))
    os.utime(image, (200, 200))
    assert ShotRepository(db_session).to_summary_response(shot)["mainImageNewerThanVideo"] is True
    assert ShotRepository(db_session).to_response(shot)["mainImageNewerThanVideo"] is True

    os.utime(video, (300, 300))
    assert freshness.main_image_newer_than_video(db_session, shot) is False
    shot.video_url = None
    assert freshness.main_image_newer_than_video(db_session, shot) is False


def test_invalidated_assembly_remains_detectable_but_clip_only_does_not(db_session, tmp_path, monkeypatch):
    image = tmp_path / "new-main.png"
    image.write_bytes(b"image")
    now = datetime.now(timezone.utc)
    os.utime(image, (now.timestamp(), now.timestamp()))
    monkeypatch.setattr(freshness, "url_to_local_path", lambda url: str(image) if url == "/api/files/new-main.png" else None)
    shot = Shot(id="invalidated-shot", chapter_id="freshness-chapter", index=1,
                image_url="/api/files/new-main.png", video_url=None)
    clip = Task(id="old-clip", shot_id=shot.id, type="shot_video", status="completed", name="Clip",
                result_url="/api/files/clip.mp4", completed_at=now - timedelta(hours=2),
                metadata_json=json.dumps({"execution_scope": "CLIP"}))
    db_session.add_all([shot, clip])
    db_session.commit()
    assert freshness.main_image_newer_than_video(db_session, shot) is False

    assembly = Task(id="old-assembly", shot_id=shot.id, type="shot_video", status="completed", name="Shot assembly",
                    completed_at=now - timedelta(hours=1),
                    metadata_json=json.dumps({"batch_shot_child": True, "batch_state": "COMPLETED"}))
    db_session.add(assembly)
    db_session.commit()
    assert ShotRepository(db_session).to_summary_response(shot)["mainImageNewerThanVideo"] is True

    os.utime(image, ((now - timedelta(hours=3)).timestamp(),) * 2)
    assert freshness.main_image_newer_than_video(db_session, shot) is False
