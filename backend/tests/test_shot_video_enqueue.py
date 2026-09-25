import pytest

from app.services import shot_video_service


@pytest.mark.asyncio
async def test_enqueue_shot_video_task_deduplicates_same_persistent_task(monkeypatch):
    queued_jobs = []
    generated = []

    class FakeWorker:
        def enqueue(self, job):
            queued_jobs.append(job)

    class FakeWorkerManager:
        def worker(self, name):
            assert name == "shot_video"
            return FakeWorker()

    async def fake_generate(task_id, *args, **kwargs):
        generated.append(task_id)

    monkeypatch.setattr(shot_video_service, "worker_manager", FakeWorkerManager())
    monkeypatch.setattr(shot_video_service, "generate_shot_video_task", fake_generate)
    shot_video_service._queued_shot_video_task_ids.clear()

    args = ("task-1", "novel-1", "chapter-1", 3, "workflow-1", "/shot.png")
    shot_video_service.enqueue_shot_video_task(*args)
    shot_video_service.enqueue_shot_video_task(*args)

    assert len(queued_jobs) == 1
    assert shot_video_service._queued_shot_video_task_ids == {"task-1"}

    await queued_jobs.pop()()

    assert generated == ["task-1"]
    assert not shot_video_service._queued_shot_video_task_ids

    shot_video_service.enqueue_shot_video_task(*args)
    assert len(queued_jobs) == 1
    shot_video_service._queued_shot_video_task_ids.clear()
