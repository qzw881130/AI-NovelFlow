from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.tasks import router
from app.api.deps import get_task_repo
from app.core.database import get_db
from app.models.task import Task
from app.repositories import TaskRepository
from app.services.task_service import TaskService


def make_client(db_session):
    app = FastAPI()
    app.include_router(router, prefix="/tasks")
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_task_repo] = lambda: TaskRepository(db_session)
    return TestClient(app)


def seed_tasks(db):
    start = datetime(2026, 10, 8)
    for i in range(75):
        db.add(Task(
            id=f"task-{i:03d}", name=f"Task {i}",
            type="shot_image" if i < 60 else "shot_video",
            status="running" if i == 74 else "completed",
            created_at=start + timedelta(seconds=i),
        ))
    db.commit()
    db.expunge_all()


def test_page_reads_only_visible_rows_and_counts_all_history(db_session, monkeypatch):
    seed_tasks(db_session)
    reconcile = AsyncMock(side_effect=AssertionError("List must not contact ComfyUI"))
    monkeypatch.setattr(TaskService, "reconcile_active_tasks", reconcile)
    loaded = []
    def record_load(task, context):
        loaded.append(task.id)
    event.listen(Task, "load", record_load)
    try:
        with make_client(db_session) as client:
            response = client.get("/tasks/page?page=2&page_size=30")
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["items"]) == len(loaded) == 30
        assert data["items"][0]["id"] == "task-044"
        assert data["total"] == data["stats"]["all"] == 75
        assert data["total_pages"] == 3
        assert data["stats"]["running"] == 1
        assert data["types"] == ["shot_image", "shot_video"]
        reconcile.assert_not_called()
    finally:
        event.remove(Task, "load", record_load)


def test_filters_apply_to_sql_page_and_type_scoped_stats(db_session):
    seed_tasks(db_session)
    with make_client(db_session) as client:
        data = client.get("/tasks/page?type=shot_video&status=running").json()["data"]
    assert [item["id"] for item in data["items"]] == ["task-074"]
    assert data["total"] == 1
    assert data["stats"]["all"] == 15
    assert data["stats"]["completed"] == 14


def test_page_validation_and_empty_results(db_session):
    with make_client(db_session) as client:
        for query in ("page=0", "page_size=0", "page_size=101"):
            assert client.get(f"/tasks/page?{query}").status_code == 422
        data = client.get("/tasks/page").json()["data"]
    assert data["items"] == []
    assert data["total"] == data["total_pages"] == data["stats"]["all"] == 0


def test_legacy_list_remains_compatible_without_remote_reconciliation(db_session, monkeypatch):
    seed_tasks(db_session)
    reconcile = AsyncMock(side_effect=AssertionError("List must not contact ComfyUI"))
    monkeypatch.setattr(TaskService, "reconcile_active_tasks", reconcile)
    with make_client(db_session) as client:
        data = client.get("/tasks/?limit=2").json()["data"]
    assert [task["id"] for task in data] == ["task-074", "task-073"]
    reconcile.assert_not_called()
