import asyncio
import json
from types import SimpleNamespace

import pytest
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


def test_review_pass_batch_updates_only_selected_shots_and_keeps_existing_notes(client, db_session):
    novel, chapter = _chapter(db_session)
    first = _shot(db_session, chapter, 1, reviewed=False, with_clip=False)
    second = _shot(db_session, chapter, 2, reviewed=False, with_clip=False)
    grid = load_grid_data(first.grid_data)
    grid.panels[0].review_status = "passed"
    grid.panels[0].review_note = "原有人工确认"
    grid.panels[1].review_status = "warning"
    first.grid_data = dump_grid_data(grid)
    db_session.commit()

    path = f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/review-pass-batch"
    response = client.post(path, json={"shot_ids": [first.id]})
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"shots": 1, "panels": 3}
    reviewed = load_grid_data(first.grid_data).panels
    assert [panel.review_status for panel in reviewed] == ["passed"] * 4
    assert reviewed[0].review_note == "原有人工确认"
    assert all(panel.review_note == "人工批量审核通过" for panel in reviewed[1:])
    assert all(panel.review_status == "pending" for panel in load_grid_data(second.grid_data).panels)


def test_review_pass_batch_rejects_incomplete_or_busy_selection_without_partial_update(client, db_session):
    novel, chapter = _chapter(db_session)
    first = _shot(db_session, chapter, 1, reviewed=False, with_clip=False)
    second = _shot(db_session, chapter, 2, reviewed=False, with_clip=False)
    path = f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/review-pass-batch"
    grid = load_grid_data(second.grid_data)
    grid.panels[0].image_url = None
    second.grid_data = dump_grid_data(grid)
    db_session.commit()
    assert client.post(path, json={"shot_ids": [first.id, second.id]}).status_code == 422
    assert all(panel.review_status == "pending" for panel in load_grid_data(first.grid_data).panels)
    assert client.post(path, json={"shot_ids": [first.id, first.id]}).status_code == 422
    db_session.add(Task(type="grid_board_image", status="running", novel_id=novel.id,
                        chapter_id=chapter.id, shot_id=first.id, name="正在生图"))
    db_session.commit()
    assert client.post(path, json={"shot_ids": [first.id]}).status_code == 409
    assert all(panel.review_status == "pending" for panel in load_grid_data(first.grid_data).panels)


def test_auto_batch_is_durable_and_gated_by_novel_mode(client, db_session, db_engine, monkeypatch):
    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1)
    second = _shot(db_session, chapter, 2)
    path = f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-batch"
    response = client.post(path, json={"shot_ids": [second.id, shot.id], "merge_chapter": True})
    assert response.status_code == 200, response.text
    task = db_session.get(Task, response.json()["data"]["taskId"])
    assert task.type == "grid_auto_batch" and task.status == "pending"
    assert json.loads(task.metadata_json)["shot_ids"] == [shot.id, second.id]
    job = db_session.query(BackgroundJob).filter(BackgroundJob.task_id == task.id).one()
    assert job.handler == "app.services.grid_auto_batch:run_grid_auto_batch"
    assert client.post(path, json={"shot_ids": [shot.id]}).status_code == 409
    old_novel, old_chapter = _chapter(db_session, mode="single")
    old_shot = Shot(chapter_id=old_chapter.id, index=1)
    db_session.add(old_shot)
    db_session.commit()
    old_path = f"/api/novels/{old_novel.id}/chapters/{old_chapter.id}/grid/auto-batch"
    assert client.post(old_path, json={"shot_ids": [old_shot.id]}).status_code == 409


def test_grid_batches_can_queue_for_other_shots_but_reject_overlap(client, db_session, db_engine, monkeypatch):
    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    first = _shot(db_session, chapter, 1, with_clip=False)
    second = _shot(db_session, chapter, 2, with_clip=False)
    third = _shot(db_session, chapter, 3, with_clip=False)
    base = f"/api/novels/{novel.id}/chapters/{chapter.id}/grid"

    first_response = client.post(f"{base}/auto-board-batch", json={"shot_ids": [first.id]})
    assert first_response.status_code == 200, first_response.text
    second_response = client.post(f"{base}/auto-batch", json={"shot_ids": [second.id]})
    assert second_response.status_code == 200, second_response.text
    step_response = client.post(f"{base}/batch", json={"step": "clips_plan", "items": [{"shot_id": third.id}]})
    assert step_response.status_code == 200, step_response.text

    assert client.post(f"{base}/auto-review-batch", json={"shot_ids": [first.id]}).status_code == 409
    assert client.post(f"{base}/auto-batch", json={"shot_ids": [third.id]}).status_code == 409
    assert client.post(f"{base}/batch", json={"step": "clips_plan", "items": [{"shot_id": second.id}]}).status_code == 409
    assert client.post(f"{base}/shots/{second.id}/clips/plan").status_code == 409


def test_finished_shot_can_be_manually_reviewed_while_auto_batch_continues(client, db_session):
    from app.services.grid_tasks import active_grid_shot_ids

    novel, chapter = _chapter(db_session)
    failed = _shot(db_session, chapter, 1, reviewed=False, with_clip=False)
    pending = _shot(db_session, chapter, 2, reviewed=False, with_clip=False)
    db_session.add(Task(type="grid_auto_batch", status="running", novel_id=novel.id,
                        chapter_id=chapter.id, name="自动批量生成 Shot",
                        metadata_json=json.dumps({"shot_ids": [failed.id, pending.id],
                                                  "shot_results": {failed.id: {"status": "failed"},
                                                                   pending.id: {"status": "running"}}})))
    db_session.commit()

    assert active_grid_shot_ids(db_session, chapter.id) == {pending.id}
    base = f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/shots"
    approved = client.patch(f"{base}/{failed.id}/panels/1/review",
                            json={"status": "passed", "note": "人工确认"})
    assert approved.status_code == 200, approved.text
    db_session.refresh(failed)
    assert load_grid_data(failed.grid_data).panels[0].review_status == "passed"
    blocked = client.patch(f"{base}/{pending.id}/panels/1/review",
                           json={"status": "passed", "note": "仍在处理"})
    assert blocked.status_code == 409


def test_manual_clip_batch_accepts_warning_and_pending_but_rejects_fail(client, db_session, db_engine, monkeypatch):
    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    ready = _shot(db_session, chapter, 1, reviewed=False, with_clip=False)
    blocked = _shot(db_session, chapter, 2, reviewed=False, with_clip=False)
    ready_grid = load_grid_data(ready.grid_data)
    ready_grid.panels[0].review_status = 'warning'
    ready.grid_data = dump_grid_data(ready_grid)
    blocked_grid = load_grid_data(blocked.grid_data)
    blocked_grid.panels[0].review_status = 'failed'
    blocked.grid_data = dump_grid_data(blocked_grid)
    db_session.commit()

    path = f'/api/novels/{novel.id}/chapters/{chapter.id}/grid/batch'
    response = client.post(path, json={'step': 'clips_plan', 'items': [{'shot_id': ready.id}]})
    assert response.status_code == 200, response.text
    rejected = client.post(path, json={'step': 'clips_plan', 'items': [{'shot_id': blocked.id}]})
    assert rejected.status_code == 409


def test_grid_preflight_settings_are_separate_and_snapshot_for_batch(client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=False, with_clip=True)
    checks = client.get('/api/config/grid-generation-checks').json()['data']
    assert checks['policy'] == {'GRID_PANEL_AI_REVIEW': True, 'GRID_PANEL_FAIL_RETRY': True}
    assert any(item['id'] == 'GRID_PANEL_NON_FAIL' and not item['configurable'] for item in checks['checks'])
    assert client.post('/api/config/', json={'gridGenerationQualityPolicy': {'unknown': False}}).status_code == 400
    response = client.post('/api/config/', json={'gridGenerationQualityPolicy': {
        'GRID_PANEL_AI_REVIEW': False, 'GRID_PANEL_FAIL_RETRY': False}})
    assert response.status_code == 200, response.text
    assert client.get('/api/config/').json()['data']['gridGenerationQualityPolicy'] == {
        'GRID_PANEL_AI_REVIEW': False, 'GRID_PANEL_FAIL_RETRY': False}

    async def unexpected_review(*_args, **_kwargs):
        raise AssertionError('自动审图已关闭')

    async def fake_clip(self, novel, chapter, shot, index, *, task=None):
        grid = load_grid_data(shot.grid_data)
        plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=grid.revision)
        plan['clip_plan'][0]['video_url'] = '/api/files/clip.mp4'
        shot.video_director_plan = dump_grid_clip_plan(grid, plan['clip_plan'])
        self._complete(task, '/api/files/clip.mp4')
        self.db.commit()

    async def fake_merge(self, novel, chapter, shot, *, task=None):
        shot.video_url = '/api/files/shot.mp4'
        self._complete(task, shot.video_url)
        self.db.commit()

    monkeypatch.setattr(grid_auto_batch, '_review_panel', unexpected_review)
    monkeypatch.setattr(GridPipeline, 'generate_clip', fake_clip)
    monkeypatch.setattr(GridPipeline, 'merge_shot', fake_merge)
    task_id = client.post(f'/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-batch',
                          json={'shot_ids': [shot.id]}).json()['data']['taskId']
    parent = db_session.get(Task, task_id)
    assert json.loads(parent.metadata_json)['grid_preflight_policy']['GRID_PANEL_AI_REVIEW'] is False
    client.post('/api/config/', json={'gridGenerationQualityPolicy': {'GRID_PANEL_AI_REVIEW': True}})
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    parent = db_session.get(Task, task_id)
    result = json.loads(parent.metadata_json)['shot_results'][shot.id]
    assert parent.status == 'completed' and result['status'] == 'completed'
    assert result['warnings'] == [f'格 {index}：PENDING' for index in range(1, 5)]
    assert all(panel.review_status == 'pending' for panel in load_grid_data(db_session.get(Shot, shot.id).grid_data).panels)


def test_disabling_general_ai_review_still_reviews_offscreen_panel(client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=False, with_clip=False)
    grid = load_grid_data(shot.grid_data)
    grid.panels[0].dialogue_indexes = [1]
    shot.grid_data = dump_grid_data(grid)
    shot.dialogues = json.dumps([{'speaker': '门外官差', 'text': '开门！', 'delivery': 'offscreen',
                                  'voice_description': 'an adult male officer outside'}], ensure_ascii=False)
    db_session.commit()
    assert client.post('/api/config/', json={'gridGenerationQualityPolicy': {
        'GRID_PANEL_AI_REVIEW': False}}).status_code == 200
    reviewed = []

    async def fake_review(_db, _parent, _shot, index):
        reviewed.append(index)
        return 'PASS', '无人出镜'

    monkeypatch.setattr(grid_auto_batch, '_review_panel', fake_review)
    task_id = client.post(f'/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-board-batch',
                          json={'shot_ids': [shot.id]}).json()['data']['taskId']
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    assert db_session.get(Task, task_id).status == 'completed'
    assert reviewed == [1]
    assert [panel.review_status for panel in load_grid_data(db_session.get(Shot, shot.id).grid_data).panels] == [
        'passed', 'pending', 'pending', 'pending']


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


@pytest.mark.parametrize("route", ["auto-batch", "auto-board-batch", "auto-review-batch"])
def test_auto_batch_keeps_warning_and_continues_without_redrawing(
        client, db_session, db_engine, monkeypatch, route):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=False, with_clip=route == "auto-batch")
    calls = []

    async def fake_review(db, parent, shot, index):
        calls.append(index)
        return "WARNING", "角色焦点存疑"

    monkeypatch.setattr(grid_auto_batch, "_review_panel", fake_review)
    if route == "auto-batch":
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

        monkeypatch.setattr(GridPipeline, "generate_clip", fake_clip)
        monkeypatch.setattr(GridPipeline, "merge_shot", fake_merge)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/{route}",
                           json={"shot_ids": [shot.id]})
    task_id = response.json()["data"]["taskId"]
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    parent = db_session.get(Task, task_id)
    assert calls == [1, 2, 3, 4]
    assert parent.status == "completed", parent.error_message
    assert parent.error_message is None
    shot_result = json.loads(parent.metadata_json)["shot_results"][shot.id]
    assert shot_result["status"] == "completed"
    assert shot_result["warnings"] == [f"格 {index}：WARNING" for index in range(1, 5)]
    assert all(panel.review_status == "warning" for panel in load_grid_data(db_session.get(Shot, shot.id).grid_data).panels)
    assert db_session.query(Task).filter(Task.parent_task_id == task_id,
                                         Task.type == "grid_panel_image").count() == 0
    if route == "auto-batch":
        assert db_session.get(Shot, shot.id).video_url == "/api/files/shot.mp4"


def test_auto_review_redraws_only_failed_panel_once(client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=False, with_clip=False)
    calls = []

    async def fake_review(db, parent, shot, index):
        calls.append(("review", index))
        return ("FAIL", "身份错位") if index == 1 and calls.count(("review", 1)) == 1 else ("PASS", "正确")

    def fake_prepare(self, novel, shot, index):
        calls.append(("prepare", index))
        grid = load_grid_data(shot.grid_data)
        grid.panels[index - 1].image_prompt = "重做此格"
        shot.grid_data = dump_grid_data(grid)
        self.db.commit()
        return {}

    async def fake_retry(self, novel, chapter, shot, index, *, task=None):
        calls.append(("redraw", index))
        grid = load_grid_data(shot.grid_data)
        grid.panels[index - 1].image_url = "/api/files/redrawn-panel.png"
        grid.panels[index - 1].review_status = "pending"
        shot.grid_data = dump_grid_data(grid)
        self._complete(task, grid.panels[index - 1].image_url)
        self.db.commit()

    monkeypatch.setattr(grid_auto_batch, "_review_panel", fake_review)
    monkeypatch.setattr(GridPipeline, "prepare_panel_retry", fake_prepare)
    monkeypatch.setattr(GridPipeline, "generate_panel_retry", fake_retry)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-review-batch",
                           json={"shot_ids": [shot.id]})
    task_id = response.json()["data"]["taskId"]
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    assert db_session.get(Task, task_id).status == "completed", (db_session.get(Task, task_id).error_message, calls)
    assert calls == [("review", 1), ("prepare", 1), ("redraw", 1),
                     ("review", 1), ("review", 2), ("review", 3), ("review", 4)]
    assert all(panel.review_status == "passed" for panel in load_grid_data(db_session.get(Shot, shot.id).grid_data).panels)


def test_grid_policy_can_disable_failed_panel_retry(client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=False, with_clip=False)
    assert client.post('/api/config/', json={'gridGenerationQualityPolicy': {
        'GRID_PANEL_FAIL_RETRY': False}}).status_code == 200

    async def fail_review(*_args, **_kwargs):
        return 'FAIL', '身份错位'

    monkeypatch.setattr(grid_auto_batch, '_review_panel', fail_review)
    task_id = client.post(f'/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-review-batch',
                          json={'shot_ids': [shot.id]}).json()['data']['taskId']
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    parent = db_session.get(Task, task_id)
    assert parent.status == 'failed'
    assert 'FAIL' in parent.error_message
    assert load_grid_data(db_session.get(Shot, shot.id).grid_data).panels[0].review_status == 'failed'
    assert db_session.query(Task).filter(Task.parent_task_id == task_id,
                                         Task.type == 'grid_panel_image').count() == 0


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
    new_parent = Task(type="grid_review_batch", status="running", novel_id=novel.id,
                      chapter_id=chapter.id, name="重新 AI 评审")
    db_session.add(new_parent)
    db_session.commit()
    third = asyncio.run(grid_auto_batch._review_panel(db_session, new_parent, shot, 1))
    assert third[0] == "PASS"
    assert len(set(calls)) == 3
    assert db_session.query(Task).filter(Task.type == "grid_panel_review", Task.shot_id == shot.id).count() == 3


def test_board_batch_plans_prompts_generates_and_stops_before_video(
        client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    first = Shot(chapter_id=chapter.id, index=1, description="抵达村庄", duration=12,
                 characters="[]", dialogues="[]")
    second = Shot(chapter_id=chapter.id, index=2, description="院前停步", duration=12,
                  characters="[]", dialogues="[]")
    db_session.add_all([first, second])
    db_session.commit()
    calls = []

    async def fake_plan(self, novel, chapter, shot, layout, *, task=None):
        calls.append((shot.index, "plan"))
        panels = [GridPanel(index=i, beat=f"节点 {i}", camera="中景") for i in range(1, 5)]
        shot.grid_data = dump_grid_data(GridShotData(revision=1, layout="2x2", seed=shot.index,
            panel_width=768, panel_height=432, panels=panels))
        self._complete(task)
        self.db.commit()

    async def fake_prepare(self, novel, chapter, shot, *, task=None):
        calls.append((shot.index, "prepare"))
        grid = load_grid_data(shot.grid_data)
        grid.board_prompt = "按四格生成"
        shot.grid_data = dump_grid_data(grid)
        self._complete(task)
        self.db.commit()

    async def fake_generate(self, novel, chapter, shot, *, task=None):
        calls.append((shot.index, "generate"))
        grid = load_grid_data(shot.grid_data)
        grid.board_image_url = f"/api/files/board-{shot.index}.png"
        for panel in grid.panels:
            panel.image_url = f"/api/files/panel-{shot.index}-{panel.index}.png"
        shot.grid_data = dump_grid_data(grid)
        self._complete(task, grid.board_image_url)
        self.db.commit()

    monkeypatch.setattr(GridPipeline, "plan_panels", fake_plan)
    monkeypatch.setattr(GridPipeline, "prepare_board", fake_prepare)
    monkeypatch.setattr(GridPipeline, "generate_board", fake_generate)
    async def fake_review(db, parent, shot, index):
        calls.append((shot.index, f"review-{index}"))
        return "PASS", "人物与道具正确"
    monkeypatch.setattr(grid_auto_batch, "_review_panel", fake_review)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-board-batch",
                           json={"shot_ids": [second.id, first.id]})
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["taskId"]
    parent = db_session.get(Task, task_id)
    assert parent.type == "grid_board_batch"
    assert db_session.query(BackgroundJob).filter(BackgroundJob.task_id == task_id).one().handler == \
        "app.services.grid_auto_batch:run_grid_auto_batch"
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    assert db_session.get(Task, task_id).status == "completed"
    assert calls == [(1, "plan"), (1, "prepare"), (1, "generate"),
                     *[(1, f"review-{index}") for index in range(1, 5)],
                     (2, "plan"), (2, "prepare"), (2, "generate"),
                     *[(2, f"review-{index}") for index in range(1, 5)]]
    assert db_session.query(Task).filter(Task.parent_task_id == task_id).count() == 6
    assert all(load_grid_data(db_session.get(Shot, shot.id).grid_data).board_image_url
               for shot in [first, second])
    assert all(all(panel.review_status == "passed" for panel in load_grid_data(db_session.get(Shot, shot.id).grid_data).panels)
               for shot in [first, second])
    assert all(not db_session.get(Shot, shot.id).video_url for shot in [first, second])


def test_review_batch_checks_existing_board_without_regeneration(client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=False, with_clip=False)
    reviewed = []

    async def fake_review(db, parent, shot, index):
        reviewed.append(index)
        return "PASS", "镜头正确"

    monkeypatch.setattr(grid_auto_batch, "_review_panel", fake_review)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-review-batch",
                           json={"shot_ids": [shot.id]})
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["taskId"]
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    assert reviewed == [1, 2, 3, 4]
    assert db_session.get(Task, task_id).status == "completed"
    assert db_session.query(Task).filter(Task.parent_task_id == task_id, Task.type == "grid_board_image").count() == 0
    assert all(panel.review_status == "passed" for panel in load_grid_data(db_session.get(Shot, shot.id).grid_data).panels)
    assert db_session.get(Shot, shot.id).video_url is None


def test_force_review_rechecks_passed_panels_and_keeps_previous_tasks(client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=True, with_clip=False)
    previous = Task(type="grid_panel_review", status="completed", novel_id=novel.id,
                    chapter_id=chapter.id, shot_id=shot.id, name="旧评审", result_url="/api/files/s1p1.png")
    db_session.add(previous)
    db_session.commit()
    seen = []

    async def fake_review(db, parent, shot, index):
        seen.append(index)
        return "PASS", "复评通过"

    monkeypatch.setattr(grid_auto_batch, "_review_panel", fake_review)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-review-batch",
                           json={"shot_ids": [shot.id], "force_review": True})
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["taskId"]
    assert json.loads(db_session.get(Task, task_id).metadata_json)["force_review"] is True
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    assert seen == [1, 2, 3, 4]
    assert db_session.get(Task, task_id).status == "completed"
    assert db_session.get(Task, previous.id).status == "completed"
    assert all(panel.review_note == "AI 复评PASS：复评通过"
               for panel in load_grid_data(db_session.get(Shot, shot.id).grid_data).panels)
    assert db_session.query(Task).filter(Task.parent_task_id == task_id,
                                         Task.type == "grid_panel_image").count() == 0


def test_force_review_fail_checks_remaining_panels_and_invalidates_video(client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=True, with_clip=True)
    shot.video_url, shot.video_status = "/api/files/shot.mp4", "completed"
    chapter.final_video = "/api/files/chapter.mp4"
    db_session.commit()
    seen = []

    async def fake_review(db, parent, shot, index):
        seen.append(index)
        return ("FAIL", "身份冲突") if index == 1 else ("PASS", "符合要求")

    monkeypatch.setattr(grid_auto_batch, "_review_panel", fake_review)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-review-batch",
                           json={"shot_ids": [shot.id], "force_review": True})
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["taskId"]
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    updated = db_session.get(Shot, shot.id)
    assert seen == [1, 2, 3, 4]
    assert db_session.get(Task, task_id).status == "failed"
    assert load_grid_data(updated.grid_data).panels[0].review_status == "failed"
    assert updated.video_url is None and db_session.get(Chapter, chapter.id).final_video is None


def test_single_panel_ai_review_only_rechecks_selected_panel(client, db_session, db_engine, monkeypatch):
    from app.services import grid_auto_batch

    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1, reviewed=True, with_clip=True)
    grid = load_grid_data(shot.grid_data)
    grid.panels[0].review_status = "failed"
    grid.panels[0].review_note = "保留其他格的审核结果"
    grid.panels[1].review_status = "warning"
    shot.grid_data = dump_grid_data(grid)
    db_session.commit()
    seen = []

    async def fake_review(db, parent, reviewed_shot, index):
        seen.append(index)
        return "PASS", "单格复评通过"

    monkeypatch.setattr(grid_auto_batch, "_review_panel", fake_review)
    path = f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/shots/{shot.id}/panels/2/ai-review"
    response = client.post(path)
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["taskId"]
    assert json.loads(db_session.get(Task, task_id).metadata_json)["panel_index"] == 2
    asyncio.run(run_grid_auto_batch(task_id))
    db_session.expire_all()
    panels = load_grid_data(db_session.get(Shot, shot.id).grid_data).panels
    assert seen == [2]
    assert db_session.get(Task, task_id).status == "completed"
    assert panels[1].review_status == "passed"
    assert panels[1].review_note == "AI 复评PASS：单格复评通过"
    assert panels[0].review_status == "failed"
    assert panels[0].review_note == "保留其他格的审核结果"
    assert panels[2].review_status == "passed"


def test_single_panel_ai_review_rejects_missing_image_and_invalid_index(client, db_session, db_engine, monkeypatch):
    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = _shot(db_session, chapter, 1)
    grid = load_grid_data(shot.grid_data)
    grid.panels[1].image_url = None
    shot.grid_data = dump_grid_data(grid)
    db_session.commit()
    base = f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/shots/{shot.id}/panels"
    assert client.post(f"{base}/2/ai-review").status_code == 409
    assert client.post(f"{base}/5/ai-review").status_code == 409
    assert db_session.query(Task).filter(Task.type == "grid_review_batch").count() == 0
    assert client.post(f"{base}/1/ai-review").status_code == 200


def test_board_batch_is_mode_gated_and_cannot_merge_chapter(client, db_session, db_engine, monkeypatch):
    _hold_worker(monkeypatch, db_engine)
    novel, chapter = _chapter(db_session)
    shot = Shot(chapter_id=chapter.id, index=1, description="空镜", characters="[]", dialogues="[]")
    db_session.add(shot)
    db_session.commit()
    path = f"/api/novels/{novel.id}/chapters/{chapter.id}/grid/auto-board-batch"
    assert client.post(path, json={"shot_ids": [shot.id], "merge_chapter": True}).status_code == 409
    old_novel, old_chapter = _chapter(db_session, mode="single")
    old_shot = Shot(chapter_id=old_chapter.id, index=1)
    db_session.add(old_shot)
    db_session.commit()
    old_path = f"/api/novels/{old_novel.id}/chapters/{old_chapter.id}/grid/auto-board-batch"
    assert client.post(old_path, json={"shot_ids": [old_shot.id]}).status_code == 409
    shot_id = shot.id
    response = client.post(path, json={"shot_ids": [shot_id]})
    assert response.status_code == 200
    source_id = response.json()["data"]["taskId"]
    source = db_session.get(Task, source_id)
    source.status = "failed"
    db_session.commit()
    retry = TaskService(db_session).retry_task(source_id)
    assert retry["success"] is True
    resumed = db_session.get(Task, retry["data"]["taskId"])
    assert resumed.type == "grid_board_batch"
    assert json.loads(resumed.metadata_json)["shot_ids"] == [shot_id]
