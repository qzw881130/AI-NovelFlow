"""Chapter image counts follow the current image and its current review."""
import json
from datetime import datetime, timedelta, timezone

from app.models.image_quality_review import ImageQualityReview
from app.models.novel import Chapter, Novel
from app.models.shot import Shot


def test_chapter_list_shot_image_stats_and_estimated_duration(client, db_session):
    novel = Novel(id="image-stats-novel", title="Novel")
    first = Chapter(id="image-stats-first", novel_id=novel.id, number=1, title="First")
    second = Chapter(id="image-stats-second", novel_id=novel.id, number=2, title="Second")
    empty = Chapter(id="image-stats-empty", novel_id=novel.id, number=3, title="Empty")
    db_session.add_all([novel, first, second, empty])
    db_session.add_all([
        Shot(id="image-stats-pass", chapter_id=first.id, index=1, duration=10, image_url="/api/files/pass.png", image_task_id="task-pass", video_url="/api/files/pass.mp4", video_status="completed"),
        Shot(id="image-stats-warning", chapter_id=first.id, index=2, duration=20, image_url="/api/files/warning.png", image_task_id="task-warning", video_status="completed"),
        Shot(id="image-stats-fail", chapter_id=first.id, index=3, duration=30, image_url="/api/files/fail.png", image_task_id="task-fail", video_url="/api/files/old.mp4", video_status="generating"),
        Shot(id="image-stats-replaced", chapter_id=first.id, index=4, duration=40, image_url="/api/files/new.png", image_task_id="task-replaced", video_url="/api/files/new.mp4", video_status="completed"),
        Shot(id="image-stats-pending", chapter_id=first.id, index=5, duration=56),
        Shot(id="image-stats-upload", chapter_id=second.id, index=1, duration=17, image_url="/api/files/upload.png", video_url="/api/files/upload.mp4", video_status="completed"),
    ])
    now = datetime.now(timezone.utc)

    def review(task_id, image_url, verdict, created_at):
        return ImageQualityReview(
            task_id=task_id, status="success", overall=verdict,
            input_snapshot_json=json.dumps({"generated_image": image_url}), created_at=created_at,
        )

    db_session.add_all([
        review("task-pass", "/api/files/pass.png", "WARNING", now - timedelta(minutes=2)),
        review("task-pass", "/api/files/pass.png", "PASS", now),
        review("task-warning", "/api/files/warning.png", "WARNING", now),
        review("task-fail", "/api/files/fail.png", "FAIL", now),
        review("task-replaced", "/api/files/old.png", "FAIL", now),
    ])
    db_session.commit()

    response = client.get(f"/api/novels/{novel.id}/chapters")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data[0]["shotImageStats"] == {
        "generated": 4, "total": 5, "passed": 1, "warning": 1, "failed": 1,
    }
    assert data[1]["shotImageStats"] == {
        "generated": 1, "total": 1, "passed": 0, "warning": 0, "failed": 0,
    }
    assert [chapter["estimatedDuration"] for chapter in data] == [156, 17, None]
    assert [chapter["shotVideoStats"] for chapter in data] == [
        {"completed": 2, "total": 5},
        {"completed": 1, "total": 1},
        {"completed": 0, "total": 0},
    ]
