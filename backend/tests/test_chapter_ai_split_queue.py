"""Batch AI splitting uses durable, bounded parallel lanes."""
import asyncio
import json

from sqlalchemy.orm import sessionmaker

from app.models.background_job import BackgroundJob
from app.models.novel import Chapter, Novel
from app.models.task import Task
from app.services.background_workers import AsyncWorker, WorkerManager
from app.services.chapter_ai_split_service import run_chapter_ai_split_task


def test_batch_split_persists_jobs_in_three_lanes(client, db_session, db_engine, monkeypatch):
    novel = Novel(title="并行拆分")
    db_session.add(novel)
    db_session.flush()
    chapters = [Chapter(novel_id=novel.id, number=index + 1, title=f"第{index + 1}章", content="正文")
                for index in range(5)]
    db_session.add_all(chapters)
    db_session.commit()

    signalled = []
    monkeypatch.setattr(AsyncWorker, "signal", lambda self, job_id: signalled.append((self.name, job_id)))
    url = f"/api/novels/{novel.id}/chapter-ai-split-batches"
    response = client.post(url, json={"chapter_ids": [chapter.id for chapter in chapters]})
    assert response.status_code == 200, response.text
    batch = response.json()["data"]
    assert batch["total"] == 5 and batch["pending"] == 5
    jobs = db_session.query(BackgroundJob).order_by(BackgroundJob.created_at, BackgroundJob.id).all()
    assert len(jobs) == 5
    assert [job.queue_name for job in jobs] == ["chapter_ai_split_0", "chapter_ai_split_1", "chapter_ai_split_2", "chapter_ai_split_0", "chapter_ai_split_1"]
    assert all(job.status == "queued" for job in jobs)
    assert all(json.loads(job.payload_json) == {"task_id": job.task_id} for job in jobs)
    assert client.post(url, json={"chapter_ids": [chapters[0].id]}).status_code == 409

    signalled.clear()
    restarted = WorkerManager(session_factory=sessionmaker(bind=db_engine))
    assert restarted.resume_persisted() == 5
    assert {job_id for _, job_id in signalled} == {job.id for job in jobs}


def test_batch_split_worker_records_success_and_failure(db_session, db_engine, monkeypatch):
    novel = Novel(title="结果")
    db_session.add(novel)
    db_session.flush()
    good = Chapter(novel_id=novel.id, number=1, title="成功章", content="正文")
    bad = Chapter(novel_id=novel.id, number=2, title="失败章", content="正文")
    batch = Task(type="chapter_ai_split_batch", status="running", novel_id=novel.id, name="批量拆分")
    db_session.add_all([good, bad, batch])
    db_session.flush()
    tasks = [Task(type="chapter_ai_split", status="pending", novel_id=novel.id,
                  chapter_id=chapter.id, parent_task_id=batch.id, name=chapter.title)
             for chapter in (good, bad)]
    db_session.add_all(tasks)
    db_session.commit()

    monkeypatch.setattr("app.services.chapter_ai_split_service.SessionLocal", sessionmaker(bind=db_engine))

    async def fake_split(self, *, chapter, **_):
        return {"success": True, "data": {"shots": [{"index": 1}]}} if chapter.id == good.id else {"success": False, "message": "模型调用失败"}

    monkeypatch.setattr("app.services.chapter_ai_split_service.NovelService.split_chapter", fake_split)
    asyncio.run(run_chapter_ai_split_task(tasks[0].id))
    db_session.expire_all()
    assert db_session.get(Task, tasks[0].id).status == "completed"
    assert db_session.get(Task, batch.id).status == "running"
    asyncio.run(run_chapter_ai_split_task(tasks[1].id))
    db_session.expire_all()
    assert db_session.get(Task, tasks[1].id).status == "failed"
    assert db_session.get(Task, tasks[1].id).error_message == "模型调用失败"
    assert db_session.get(Task, batch.id).status == "failed"
    assert db_session.get(Task, batch.id).progress == 100
