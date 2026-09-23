import json
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


def test_chapter_video_assets_are_grouped_by_target_megapixels(db_session, monkeypatch, tmp_path):
    novel = Novel(title="多目标章回")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章")
    db_session.add(chapter)
    db_session.flush()
    from app.models.shot import Shot
    db_session.add_all([
        Shot(chapter_id=chapter.id, index=1),
        Shot(chapter_id=chapter.id, index=2),
    ])
    paths = {}
    for profile, target in [("draft", None), ("hd10", 1.0), ("hd12", 1.2)]:
        path = tmp_path / f"{profile}.mp4"
        path.write_bytes(profile.encode())
        url = f"/api/files/{profile}.mp4"
        paths[url] = str(path)
        metadata = {"video_variant": "draft" if target is None else "hd", "target_megapixels": target, "is_final_video": True, "shots_count": 2}
        db_session.add(Task(type="chapter_video", status="completed", name=profile, chapter_id=chapter.id, novel_id=novel.id, result_url=url, metadata_json=json.dumps(metadata)))
    db_session.commit()
    monkeypatch.setattr("app.repositories.chapter_repository.url_to_local_path", lambda url: paths.get(url))

    from app.repositories.chapter_repository import ChapterRepository
    assets = ChapterRepository(db_session).get_chapter_video_assets(chapter)

    assert [asset["profileKey"] for asset in assets] == ["draft", "hd:1.0", "hd:1.2"]
    assert [asset["label"] for asset in assets] == ["初稿", "高清 1 MP", "高清 1.2 MP"]


def test_create_hd_novel_video_merge_uses_only_hd_chapter_videos(client, db_session, monkeypatch, tmp_path):
    novel = Novel(title="高清章回合并")
    db_session.add(novel)
    db_session.flush()
    chapters = [
        Chapter(novel_id=novel.id, number=index, title=f"第{index}章", final_video=f"/api/files/draft-{index}.mp4", hd_final_video=f"/api/files/hd-{index}.mp4")
        for index in (1, 2)
    ]
    db_session.add_all(chapters)
    db_session.flush()
    paths = {}
    for chapter in chapters:
        path = tmp_path / f"hd-{chapter.number}.mp4"
        path.write_bytes(b"hd")
        paths[chapter.hd_final_video] = str(path)
        db_session.add(Task(
            type="chapter_video",
            status="completed",
            novel_id=novel.id,
            chapter_id=chapter.id,
            result_url=chapter.hd_final_video,
            name=f"hd chapter {chapter.number}",
            metadata_json='{"video_variant":"hd","target_megapixels":1.0,"is_final_video":true,"shots_count":1}',
        ))
    db_session.commit()
    monkeypatch.setattr("app.api.novel_videos.url_to_local_path", lambda url: paths.get(url))
    monkeypatch.setattr("app.repositories.chapter_repository.url_to_local_path", lambda url: paths.get(url))
    worker = MagicMock()
    monkeypatch.setattr("app.api.novel_videos.worker_manager.worker", lambda _: worker)

    response = client.post(
        f"/api/novels/{novel.id}/video-merges",
        json={"chapter_ids": [chapter.id for chapter in chapters], "video_variant": "hd", "target_megapixels": 1.0},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["videoVariant"] == "hd"
    assert [item["videoUrl"] for item in data["chapters"]] == [chapter.hd_final_video for chapter in chapters]


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
        lambda self, chapter, video_variant="draft", target_megapixels=None: {"chapterVideoUrl": chapter.final_video},
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
