import asyncio
import json
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models.background_job import BackgroundJob
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.schemas.grid_shot import GridPanel, GridShotData, dump_grid_clip_plan, dump_grid_data, load_grid_data, read_grid_clip_plan
from app.services.background_workers import worker_manager
from app.services.grid_auto_batch import run_grid_auto_batch
from app.services.grid_pipeline import GridPipeline, GridPipelineError
from app.services.task_service import TaskService


def _chapter(db, *, mode="grid"):
    novel = Novel(title="批量测试", video_mode=mode)
    db.add(novel)
    db.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="黄昏投宿", content="门前交谈。")
    db.add(chapter)
    db.commit()
    return novel, chapter


def _shot(db, chapter, index, *, reviewed=True, with_clip=True):
    shot = Shot(chapter_id=chapter.id, index=index, description=f"Shot {index}", duration=8,
                characters='[]', dialogues='[]')
    panels = [GridPanel(index=i, beat=f"节点 {i}", camera="中景", image_url=f"/api/files/s{index}p{i}.png",
                        review_status="passed" if reviewed else "pending") for i in range(1, 5)]
    grid = GridShotData(revision=1, layout="2x2", seed=index, panel_width=768, panel_height=432,
                        panels=panels, board_image_url=f"/api/files/s{index}board.png", board_prompt="宫格提示词")
    shot.grid_data = dump_grid_data(grid)
    if with_clip:
        shot.video_director_plan = dump_grid_clip_plan(grid, [{"clip_index": 1, "duration": 8,
            "panel_indexes": [1, 2, 3, 4], "reference_strategy": "split_panels",
            "dialogues": [], "prompt": "已验证六段式提示词"}])
    db.add(shot)
    db.commit()
    return shot


def _hold_worker(monkeypatch, engine):
    class HoldWorker:
        def enqueue(self, request, *, db):
            worker_manager.persist(request, "grid", db=db)
    monkeypatch.setattr(worker_manager, "worker", lambda name: HoldWorker())
    monkeypatch.setattr(worker_manager, "_session_factory", lambda: Session(engine))


def test_auto_batch_is_durable_and_gated_by_novel_mode(client, db_session, db_engine, monkeypatch):
    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1)
    path = f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-batch"
    response = client.post(path, json={"shot_ids": [shot.id], "merge_chapter": True})
    assert response.status_code == 200, response.text
    task = db_session.get(Task, response.json()["data"]["taskId"])
    assert task.type == "grid_auto_batch" and task.status == "pending"
    job = db_session.query(BackgroundJob).filter(BackgroundJob.task_id == task.id).one()
    assert job.handler == "app.services.grid_auto_batch:run_grid_auto_batch"
    assert client.post(path, json={"shot_ids": [shot.id]}).status_code == 409
    old_novel, old_chapter = _chapter(db_session, mode="single")
    old_shot = Shot(chapter_id=old_chapter.id, index=1)
    db_session.add(old_shot)
    db_session.commit()
    old_path = f"/api/novels/{old_novel.id}/chapters/{old_chapter.id}/grid/auto-batch"
    assert client.post(old_path, json={"shot_ids": [old_shot.id]}).status_code == 409


def test_auto_batch_continues_other_shots_after_clip_failure(client, db_session, db_engine, monkeypatch):
    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    first, second = _shot(db_session, chapter, 1), _shot(db_session, chapter, 2)

    async def fake_clip(self, novel, chapter, shot, index, *, task=None):
        if shot.index == 1:
            raise GridPipelineError("模拟 H3 失败")
        grid = load_grid_data(shot.grid_data)
        plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=grid.revision)
        plan["clip_plan"][0]["video_url"] = "/api/files/second.mp4"
        shot.video_director_plan = dump_grid_clip_plan(grid, plan["clip_plan"])
        self._complete(task, "/api/files/second.mp4")
        self.db.commit()

    async def fake_merge(self, novel, chapter, shot, *, task=None):
        shot.video_url = "/api/files/merged.mp4"
        self._complete(task, shot.video_url)
        self.db.commit()

    monkeypatch.setattr(GridPipeline, "generate_clip", fake_clip)
    monkeypatch.setattr(GridPipeline, "merge_shot", fake_merge)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-batch",
                           json={"shot_ids": [first.id, second.id]})
    task_id = response.json()["data"]["taskId"]
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    parent = db_session.get(Task, task_id)
    results = json.loads(parent.metadata_json)["shot_results"]
    assert parent.status == "failed"
    assert results[first.id]["status"] == "failed"
    assert results[second.id]["status"] == "completed"
    assert db_session.get(Shot, second.id).video_url == "/api/files/merged.mp4"
    assert db_session.query(Task).filter(Task.parent_task_id == task_id,
                                         Task.type == "grid_shot_merge").count() == 1
    retry = TaskService(db_session).retry_task(task_id)
    assert retry["success"] is True
    retried = db_session.get(Task, retry["data"]["taskId"])
    assert retried.source_task_id == task_id
    assert json.loads(retried.metadata_json)["shot_ids"] == [first.id]
    assert db_session.query(BackgroundJob).filter(BackgroundJob.task_id == retried.id).count() == 1


def test_auto_batch_reviews_each_panel_and_stops_on_unresolved_warning(
        client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=False, with_clip=False)
    calls = []

    async def fake_review(db, parent, shot, index):
        calls.append(index)
        return "WARNING", "角色焦点存疑"

    def fake_prepare(self, novel, shot, index):
        grid = load_grid_data(shot.grid_data)
        grid.panels[index - 1].image_prompt = "重做此格"
        shot.grid_data = dump_grid_data(grid)
        self.db.commit()
        return {}

    async def fake_retry(self, novel, chapter, shot, index, *, task=None):
        grid = load_grid_data(shot.grid_data)
        grid.panels[index - 1].image_url = "/api/files/new-panel.png"
        grid.panels[index - 1].review_status = "pending"
        shot.grid_data = dump_grid_data(grid)
        self._complete(task, grid.panels[index - 1].image_url)
        self.db.commit()

    monkeypatch.setattr(grid_auto_batch, "_review_panel", fake_review)
    monkeypatch.setattr(GridPipeline, "prepare_panel_retry", fake_prepare)
    monkeypatch.setattr(GridPipeline, "generate_panel_retry", fake_retry)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-batch",
                           json={"shot_ids": [shot.id]})
    task_id = response.json()["data"]["taskId"]
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    parent = db_session.get(Task, task_id)
    assert calls == [1, 1]
    assert parent.status == "failed"
    assert json.loads(parent.metadata_json)["shot_results"][shot.id]["status"] == "needs_review"
    assert load_grid_data(db_session.get(Shot, shot.id).grid_data).panels[0].review_status == "warning"
    assert db_session.query(Task).filter(Task.parent_task_id == task_id,
                                         Task.type == "grid_clips_plan").count() == 0


def test_auto_batch_can_approve_panel_from_ai_pass(client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=False, with_clip=True)

    async def fake_review(db, task_id, trigger):
        task = db.get(Task, task_id)
        assert task.type == "grid_panel_review" and task.result_url and "本格" in task.prompt_text
        return SimpleNamespace(status="success", overall="PASS", summary="主体和道具正确")

    async def fake_clip(self, novel, chapter, shot, index, *, task=None):
        grid = load_grid_data(shot.grid_data)
        plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=grid.revision)
        plan["clip_plan"][0]["video_url"] = "/api/files/clip.mp4"
        shot.video_director_plan = dump_grid_clip_plan(grid, plan["clip_plan"])
        self._complete(task, "/api/files/clip.mp4")
        self.db.commit()

    async def fake_merge(self, novel, chapter, shot, *, task=None):
        shot.video_url = "/api/files/shot.mp4"
        self._complete(task, shot.video_url)
        self.db.commit()

    monkeypatch.setattr(grid_auto_batch, "review_image_task", fake_review)
    monkeypatch.setattr(GridPipeline, "generate_clip", fake_clip)
    monkeypatch.setattr(GridPipeline, "merge_shot", fake_merge)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-batch",
                           json={"shot_ids": [shot.id]})
    task_id = response.json()["data"]["taskId"]
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    assert db_session.get(Task, task_id).status == "completed"
    assert all(panel.review_status == "passed" for panel in load_grid_data(db_session.get(Shot, shot.id).grid_data).panels)
    summary = client.get(f"/api/tasks/?chapter_id={chapter.id}&summary=true&limit=100").json()["data"]
    assert next(item for item in summary if item["id"] == task_id)["autoShotResults"][shot.id]["status"] == "completed"


def test_panel_review_uses_new_task_after_same_url_image_retry(client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=False)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-batch",
                           json={"shot_ids": [shot.id]})
    parent = db_session.get(Task, response.json()["data"]["taskId"])
    calls = []

    async def fake_review(db, task_id, trigger):
        calls.append(task_id)
        return SimpleNamespace(status="success", overall="WARNING" if len(calls) == 1 else "PASS",
                               summary="已检查")

    monkeypatch.setattr(grid_auto_batch, "review_image_task", fake_review)
    first = asyncio.run(grid_auto_batch._review_panel(db_session, parent, shot, 1))
    grid = load_grid_data(shot.grid_data)
    grid.panels[0].image_task_id = "new-image-task"
    shot.grid_data = dump_grid_data(grid)
    db_session.commit()
    second = asyncio.run(grid_auto_batch._review_panel(db_session, parent, shot, 1))
    assert first[0] == "WARNING" and second[0] == "PASS"
    assert len(set(calls)) == 2
