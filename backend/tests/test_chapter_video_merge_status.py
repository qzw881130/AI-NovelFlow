"""Chapter merge reminder follows the currently selected draft Shot videos."""

from datetime import datetime

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task


def test_chapter_merge_status_tracks_unmerged_and_newer_shot_videos(client, db_session):
    novel = Novel(title="测试小说")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1)
    db_session.add(shot)
    db_session.commit()

    url = f"/api/novels/{novel.id}/chapters/{chapter.id}/merge-video-status"
    assert client.get(url).json()["data"]["needsMerge"] is False

    first_video = Task(
        type="shot_video", status="completed", name="Shot 1",
        chapter_id=chapter.id, shot_id=shot.id, result_url="/videos/first.mp4",
        completed_at=datetime(2026, 10, 19, 10, 0),
    )
    db_session.add(first_video)
    db_session.flush()
    shot.video_url = first_video.result_url
    shot.video_task_id = first_video.id
    db_session.commit()
    unmerged = client.get(url).json()["data"]
    assert unmerged == {
        "needsMerge": True, "reason": "not_merged", "shotCount": 1, "newerShotCount": 0,
    }

    merge = Task(
        type="chapter_video", status="completed", name="合并章节视频",
        chapter_id=chapter.id, result_url="/videos/chapter.mp4",
        completed_at=datetime(2026, 10, 19, 10, 5),
    )
    db_session.add(merge)
    chapter.final_video = merge.result_url
    db_session.commit()
    assert client.get(url).json()["data"]["needsMerge"] is False

    second_video = Task(
        type="shot_video", status="completed", name="Shot 1 again",
        chapter_id=chapter.id, shot_id=shot.id, result_url="/videos/second.mp4",
        completed_at=datetime(2026, 10, 19, 10, 10),
    )
    db_session.add(second_video)
    db_session.flush()
    shot.video_url = second_video.result_url
    shot.video_task_id = second_video.id
    db_session.commit()
    stale = client.get(url).json()["data"]
    assert stale == {
        "needsMerge": True, "reason": "shot_video_newer", "shotCount": 1, "newerShotCount": 1,
    }


def test_chapter_merge_status_uses_current_assembly_time(client, db_session):
    novel = Novel(title="测试小说")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章", final_video="/videos/chapter.mp4")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id, index=1, video_url="/videos/assembled.mp4",
        video_director_plan='{"merged_video_url":"/videos/assembled.mp4","merged_at":"2026-10-19T10:10:00"}',
    )
    db_session.add_all([
        shot,
        Task(
            type="chapter_video", status="completed", name="合并章节视频",
            chapter_id=chapter.id, result_url=chapter.final_video,
            completed_at=datetime(2026, 10, 19, 10, 5),
        ),
    ])
    db_session.commit()

    url = f"/api/novels/{novel.id}/chapters/{chapter.id}/merge-video-status"
    assert client.get(url).json()["data"]["newerShotCount"] == 1
