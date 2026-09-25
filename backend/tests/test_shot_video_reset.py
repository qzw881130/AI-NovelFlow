import json

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task


def test_reset_shot_video_data_clears_video_stage_but_keeps_shot_image(client, db_session, monkeypatch):
    novel = Novel(title="reset video stage")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="chapter")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id,
        index=4,
        image_url="/api/files/story_test/chapter_test/shots/main.png",
        video_url="/api/files/story_test/chapter_test/videos/shot_004_old.mp4",
        video_status="completed",
        video_director_plan=json.dumps({
            "clip_plan_revision": 4,
            "clip_plan": [{"clip_index": 1, "video_url": "/api/files/story_test/chapter_test/videos/clip.mp4"}],
            "keyframes": [{"index": 1, "role": "START", "image_url": "/api/files/story_test/chapter_test/shots/kf.png"}],
            "assembly_status": "COMPLETED",
        }),
        keyframes=json.dumps([{"frame_index": 0, "image_url": "/api/files/story_test/chapter_test/shots/kf.png"}]),
    )
    db_session.add(shot)
    db_session.flush()
    batch = Task(type="shot_video_batch", status="completed", name="batch", novel_id=novel.id, chapter_id=chapter.id)
    db_session.add(batch)
    db_session.flush()
    db_session.add_all([
        Task(type="shot_video", status="completed", name="shot", novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id, parent_task_id=batch.id, result_url="/api/files/story_test/chapter_test/videos/clip.mp4", metadata_json=json.dumps({"execution_scope": "CLIP"})),
        Task(type="keyframe_image", status="completed", name="keyframe", novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id, result_url="/api/files/story_test/chapter_test/shots/kf.png"),
    ])
    db_session.commit()

    monkeypatch.setattr("app.api.shots.file_storage.delete_shot_video", lambda *args, **kwargs: True)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/reset-video-data")

    assert response.status_code == 200
    db_session.refresh(shot)
    assert shot.image_url
    assert shot.video_url is None
    assert shot.video_status == "pending"
    assert json.loads(shot.video_director_plan) == {}
    assert json.loads(shot.keyframes) == []
    assert db_session.query(Task).filter(Task.shot_id == shot.id).count() == 0
    assert db_session.query(Task).filter(Task.id == batch.id).count() == 0
