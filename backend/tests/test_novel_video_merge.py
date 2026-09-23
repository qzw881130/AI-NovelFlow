from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.novel import Chapter, Novel
from app.models.task import Task
from app.services.novel_video_merge_service import run_novel_video_merge_task


def test_create_and_list_novel_video_merge(client, db_session, monkeypatch, tmp_path):
    novel = Novel(title="测试小说")
    db_session.add(novel)
    db_session.flush()
    chapters = [
        Chapter(novel_id=novel.id, number=1, title="第一章"),
        Chapter(novel_id=novel.id, number=2, title="第二章"),
    ]
    db_session.add_all(chapters)
    db_session.flush()
    for index, chapter in enumerate(chapters, 1):
        video_path = tmp_path / f"chapter-{index}.mp4"
        video_path.write_bytes(f"video-{index}".encode())
        video_url = f"/api/files/chapter-{index}.mp4"
        chapter.final_video = video_url
        db_session.add(Task(
            type="chapter_video",
            status="completed",
            novel_id=novel.id,
            chapter_id=chapter.id,
            result_url=video_url,
            name=f"chapter {index}",
            metadata_json='{"is_final_video": true, "shots_count": 1}',
        ))
    db_session.commit()

    paths = {
        "/api/files/chapter-1.mp4": str(tmp_path / "chapter-1.mp4"),
        "/api/files/chapter-2.mp4": str(tmp_path / "chapter-2.mp4"),
    }
    monkeypatch.setattr("app.api.novel_videos.url_to_local_path", lambda url: paths.get(url))
    monkeypatch.setattr("app.repositories.chapter_repository.url_to_local_path", lambda url: paths.get(url))
    worker = MagicMock()
    monkeypatch.setattr("app.api.novel_videos.worker_manager.worker", lambda _: worker)

    response = client.post(
        f"/api/novels/{novel.id}/video-merges",
        json={"chapter_ids": [chapters[1].id, chapters[0].id]},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "pending"
    assert [item["number"] for item in data["chapters"]] == [1, 2]
    worker.enqueue.assert_called_once()

    history = client.get(f"/api/novels/{novel.id}/video-merges")
    assert history.status_code == 200
    assert len(history.json()["data"]) == 1
    assert history.json()["data"][0]["id"] == data["id"]


def test_novel_video_merge_rejects_chapters_without_final_video(client, db_session):
    novel = Novel(title="测试小说")
    db_session.add(novel)
    db_session.flush()
    chapters = [
        Chapter(novel_id=novel.id, number=1, title="第一章"),
        Chapter(novel_id=novel.id, number=2, title="第二章"),
    ]
    db_session.add_all(chapters)
    db_session.commit()

    response = client.post(
        f"/api/novels/{novel.id}/video-merges",
        json={"chapter_ids": [chapter.id for chapter in chapters]},
    )

    assert response.status_code == 400
    assert "没有可用的章回视频" in response.json()["detail"]


@pytest.mark.asyncio
async def test_novel_video_merge_task_orders_chapters_and_persists_history(db_session, db_engine, monkeypatch, tmp_path):
    novel = Novel(title="测试小说")
    db_session.add(novel)
    db_session.flush()
    first = Chapter(novel_id=novel.id, number=1, title="第一章", final_video="/api/files/first.mp4")
    second = Chapter(novel_id=novel.id, number=2, title="第二章", final_video="/api/files/second.mp4")
    db_session.add_all([first, second])
    db_session.flush()
    task = Task(
        type="novel_video",
        status="pending",
        novel_id=novel.id,
        name="合并测试",
        metadata_json=f'{{"chapter_ids": ["{second.id}", "{first.id}"]}}',
    )
    db_session.add(task)
    db_session.commit()

    first_path = tmp_path / "first.mp4"
    second_path = tmp_path / "second.mp4"
    first_path.write_bytes(b"first-video")
    second_path.write_bytes(b"second-video")
    paths = {
        first.final_video: str(first_path),
        second.final_video: str(second_path),
    }
    received_paths = []

    async def fake_merge(video_paths, output_path, transition_videos=None):
        received_paths.extend(video_paths)
        Path(output_path).write_bytes(b"merged-video")
        return {"success": True}

    testing_session = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.services.novel_video_merge_service.SessionLocal", testing_session)
    monkeypatch.setattr("app.services.novel_video_merge_service.url_to_local_path", lambda url: paths.get(url))
    monkeypatch.setattr(
        "app.services.novel_video_merge_service.ChapterRepository.get_final_chapter_video_info",
        lambda self, chapter: {"chapterVideoUrl": chapter.final_video},
    )
    monkeypatch.setattr("app.services.novel_video_merge_service.file_storage._get_story_dir", lambda _: tmp_path / "story")
    monkeypatch.setattr("app.services.novel_video_merge_service.file_storage.merge_videos", fake_merge)
    monkeypatch.setattr("app.services.novel_video_merge_service.local_path_to_url", lambda _: "/api/files/merged.mp4")
    monkeypatch.setattr("app.services.novel_video_merge_service.ChapterRepository._probe_video_duration", lambda self, _: 12.5)

    await run_novel_video_merge_task(task.id)

    db_session.expire_all()
    completed = db_session.query(Task).filter(Task.id == task.id).one()
    assert received_paths == [str(first_path), str(second_path)]
    assert completed.status == "completed"
    assert completed.result_url == "/api/files/merged.mp4"
    assert completed.progress == 100
    assert '"duration": 12.5' in completed.metadata_json
