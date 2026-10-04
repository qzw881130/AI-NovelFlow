"""Cancellation tests use only isolated SQLite and fake provider requests."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.orm import sessionmaker

from app.api.llm_logs import LLMLogCancelRequest, cancel_selected_llm_logs, router
from app.core import database
from app.models.llm_log import LLMLog
from app.services.llm.base import LLMConfig, create_llm_log, update_llm_log
from app.services.llm import cancellation
from app.services.llm.cancellation import LLMCallTerminated, LLM_CANCELLED_MESSAGE, await_cancellable_llm_request


@pytest.fixture
def llm_db(db_engine, monkeypatch):
    factory = sessionmaker(bind=db_engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(cancellation, "POLL_INTERVAL", 0.01)
    return factory


def add_log(db, id_, status="pending"):
    db.add(LLMLog(id=id_, provider="custom", model="test", user_prompt="test",
                  status=status, response="kept" if status == "success" else None,
                  created_at=datetime.utcnow()))
    db.commit()


def test_cancel_only_selected_pending_and_repeat_is_idempotent(llm_db):
    with llm_db() as db:
        for id_, status in [("running", "pending"), ("other", "pending"), ("done", "success"), ("failed", "error")]:
            add_log(db, id_, status)
        result = cancel_selected_llm_logs(LLMLogCancelRequest(ids=["running", "running", "done", "failed"]), db)
        assert result["data"] == {"cancelled_ids": ["running"], "skipped_ids": ["done", "failed"]}
        db.expire_all()
        assert db.get(LLMLog, "running").error_message == LLM_CANCELLED_MESSAGE
        assert db.get(LLMLog, "running").duration >= 0
        assert db.get(LLMLog, "other").status == "pending"
        assert db.get(LLMLog, "done").response == "kept"
        assert db.get(LLMLog, "failed").error_message is None
        repeated = cancel_selected_llm_logs(LLMLogCancelRequest(ids=["running"]), db)
        assert repeated["data"]["cancelled_ids"] == []


def test_unknown_id_refuses_without_partial_cancellation(llm_db):
    with llm_db() as db:
        add_log(db, "running")
        with pytest.raises(HTTPException) as error:
            cancel_selected_llm_logs(LLMLogCancelRequest(ids=["running", "missing"]), db)
        assert error.value.status_code == 404
        db.expire_all()
        assert db.get(LLMLog, "running").status == "pending"


@pytest.mark.asyncio
async def test_endpoint_validation_and_response_without_app_startup(llm_db):
    app = FastAPI()
    app.include_router(router, prefix="/api/llm-logs")
    def get_test_db():
        with llm_db() as db:
            yield db
    app.dependency_overrides[database.get_db] = get_test_db
    with llm_db() as db:
        add_log(db, "running")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for ids in [[], ["running"] * 201]:
            response = await client.post("/api/llm-logs/cancel-selected", json={"ids": ids})
            assert response.status_code == 422
        response = await client.post("/api/llm-logs/cancel-selected", json={"ids": ["running"]})
        assert response.status_code == 200
        assert response.json()["data"]["cancelled_ids"] == ["running"]


@pytest.mark.asyncio
async def test_cancellation_interrupts_exact_request_and_preserves_other(llm_db):
    with llm_db() as db:
        add_log(db, "selected")
        add_log(db, "other")
    selected_started, other_started, selected_closed, release_other = [asyncio.Event() for _ in range(4)]
    async def selected_request():
        selected_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            selected_closed.set()
    async def other_request():
        other_started.set()
        await release_other.wait()
        return "other result"
    first = asyncio.create_task(await_cancellable_llm_request("selected", selected_request()))
    second = asyncio.create_task(await_cancellable_llm_request("other", other_request()))
    await asyncio.wait_for(selected_started.wait(), 1)
    await asyncio.wait_for(other_started.wait(), 1)
    # Independent session simulates another backend worker's persisted signal.
    with llm_db() as db:
        cancel_selected_llm_logs(LLMLogCancelRequest(ids=["selected"]), db)
    with pytest.raises(LLMCallTerminated):
        await asyncio.wait_for(first, 1)
    assert selected_closed.is_set()
    assert not second.done()
    release_other.set()
    assert await second == "other result"


def test_late_completion_cannot_overwrite_cancellation(llm_db):
    log_id = create_llm_log("custom", "test", "system", "user")
    with llm_db() as db:
        cancel_selected_llm_logs(LLMLogCancelRequest(ids=[log_id]), db)
    with pytest.raises(LLMCallTerminated):
        update_llm_log(log_id, status="success", response="late response", duration=12)
    with llm_db() as db:
        log = db.get(LLMLog, log_id)
        assert log.status == "error"
        assert log.error_message == LLM_CANCELLED_MESSAGE
        assert log.response is None


def test_completion_winning_cancel_race_is_preserved(llm_db, monkeypatch):
    from sqlalchemy.orm import Query
    original_update = Query.update
    raced = False
    def update_with_completion(query, values, **kwargs):
        nonlocal raced
        if values.get(LLMLog.error_message) == LLM_CANCELLED_MESSAGE and not raced:
            raced = True
            with llm_db() as other:
                original_update(other.query(LLMLog).filter(LLMLog.id == "running"), {
                    LLMLog.status: "success", LLMLog.response: "finished first",
                }, synchronize_session=False)
                other.commit()
        return original_update(query, values, **kwargs)
    with llm_db() as db:
        add_log(db, "running")
        monkeypatch.setattr(Query, "update", update_with_completion)
        result = cancel_selected_llm_logs(LLMLogCancelRequest(ids=["running"]), db)
        assert result["data"] == {"cancelled_ids": [], "skipped_ids": ["running"]}
        db.expire_all()
        assert db.get(LLMLog, "running").status == "success"
        assert db.get(LLMLog, "running").response == "finished first"


@pytest.mark.asyncio
async def test_response_finishing_after_cancel_is_discarded(llm_db):
    with llm_db() as db:
        add_log(db, "running")
    async def late_response():
        with llm_db() as db:
            cancel_selected_llm_logs(LLMLogCancelRequest(ids=["running"]), db)
        return "must not reach business code"
    with pytest.raises(LLMCallTerminated):
        await await_cancellable_llm_request("running", late_response())


@pytest.mark.asyncio
async def test_cancelled_before_send_does_not_start_request(llm_db):
    with llm_db() as db:
        add_log(db, "selected")
        cancel_selected_llm_logs(LLMLogCancelRequest(ids=["selected"]), db)
    started = False
    async def request():
        nonlocal started
        started = True
    with pytest.raises(LLMCallTerminated):
        await await_cancellable_llm_request("selected", request())
    assert not started


@pytest.mark.asyncio
async def test_caller_cancellation_drains_request(llm_db):
    with llm_db() as db:
        add_log(db, "selected")
    started, closed = asyncio.Event(), asyncio.Event()
    async def request():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
    task = asyncio.create_task(await_cancellable_llm_request("selected", request()))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    with llm_db() as db:
        log = db.get(LLMLog, "selected")
        assert log.status == "error" and log.error_message == "LLM 请求已中断"
        result = cancel_selected_llm_logs(LLMLogCancelRequest(ids=["selected"]), db)
        assert result["data"] == {"cancelled_ids": [], "skipped_ids": ["selected"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["custom", "anthropic", "gemini", "ollama"])
async def test_every_provider_aborts_instead_of_returning_fallback(provider_name, llm_db, monkeypatch):
    from app.services.llm.client import LLMClient
    started, closed = asyncio.Event(), asyncio.Event()
    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            closed.set()
        async def post(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.test")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    client = LLMClient(LLMConfig(provider=provider_name, model="test", api_url="http://fake.test", api_key="fake"))
    task = asyncio.create_task(client.chat_completion("system", "user"))
    await asyncio.wait_for(started.wait(), 1)
    with llm_db() as db:
        log = db.query(LLMLog).one()
        cancel_selected_llm_logs(LLMLogCancelRequest(ids=[log.id]), db)
    with pytest.raises(LLMCallTerminated):
        await asyncio.wait_for(task, 1)
    assert closed.is_set()
    if provider_name in ("custom", "ollama"):
        import os
        assert os.environ["HTTP_PROXY"] == "http://proxy.test"


@pytest.mark.asyncio
async def test_character_parse_stops_without_creating_resources(llm_db, monkeypatch):
    from app.services.novel_service import NovelService
    from app.models.novel import Character
    with llm_db() as db:
        service = NovelService.__new__(NovelService)
        service.db = db
        class StoppedLLM:
            async def parse_novel_text(self, *args, **kwargs):
                raise LLMCallTerminated(LLM_CANCELLED_MESSAGE)
        monkeypatch.setattr(service, "get_llm_service", lambda: StoppedLLM())
        monkeypatch.setattr(service, "_resolve_parse_template", lambda *args: None)
        result = await service.parse_characters("novel", [SimpleNamespace(content="story", number=1)])
        assert not result["success"]
        assert LLM_CANCELLED_MESSAGE in result["message"]
        assert db.query(Character).count() == 0


@pytest.mark.parametrize("status,error_message", [("success", None), ("error", "late network failure")])
def test_any_late_result_preserves_cancelled_terminal(llm_db, status, error_message):
    log_id = create_llm_log("custom", "test", "system", "user")
    with llm_db() as db:
        cancel_selected_llm_logs(LLMLogCancelRequest(ids=[log_id]), db)
        before = db.get(LLMLog, log_id)
        original_duration = before.duration
    with pytest.raises(LLMCallTerminated):
        update_llm_log(log_id, status=status, response="late", error_message=error_message, duration=99)
    with llm_db() as db:
        log = db.get(LLMLog, log_id)
        assert (log.status, log.error_message, log.response, log.duration) == (
            "error", LLM_CANCELLED_MESSAGE, None, original_duration,
        )


@pytest.mark.parametrize("winner", ["cancelled", "success", "error"])
def test_stale_cleanup_cannot_overwrite_terminal_winner(llm_db, monkeypatch, winner):
    from datetime import timedelta
    from sqlalchemy.orm import Query
    from app.api.llm_logs import reconcile_stale_pending_llm_logs
    with llm_db() as db:
        add_log(db, "stale")
        log = db.get(LLMLog, "stale")
        log.created_at = datetime.utcnow() - timedelta(days=1)
        db.commit()
    original_all = Query.all
    raced = False
    def all_with_terminal_race(query):
        nonlocal raced
        rows = original_all(query)
        if not raced and any(isinstance(row, LLMLog) and row.id == "stale" for row in rows):
            raced = True
            if winner == "cancelled":
                with llm_db() as other:
                    cancel_selected_llm_logs(LLMLogCancelRequest(ids=["stale"]), other)
            else:
                update_llm_log("stale", status=winner, response="completed first" if winner == "success" else None,
                               error_message="failed first" if winner == "error" else None)
        return rows
    monkeypatch.setattr(Query, "all", all_with_terminal_race)
    with llm_db() as db:
        assert reconcile_stale_pending_llm_logs(db) == 0
        db.expire_all()
        log = db.get(LLMLog, "stale")
        if winner == "cancelled":
            assert log.status == "error" and log.error_message == LLM_CANCELLED_MESSAGE
        elif winner == "success":
            assert log.status == "success" and log.response == "completed first"
        else:
            assert log.status == "error" and log.error_message == "failed first"


@pytest.mark.asyncio
@pytest.mark.parametrize("late_error", [False, True])
async def test_request_ignoring_physical_cancel_cannot_return_late_result(llm_db, late_error):
    with llm_db() as db:
        add_log(db, "selected")
    started = asyncio.Event()
    async def ignores_cancel():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if late_error:
                raise RuntimeError("late transport error")
            return "late physical success"
    request = asyncio.create_task(await_cancellable_llm_request("selected", ignores_cancel()))
    await asyncio.wait_for(started.wait(), 1)
    with llm_db() as db:
        cancel_selected_llm_logs(LLMLogCancelRequest(ids=["selected"]), db)
    with pytest.raises(LLMCallTerminated):
        await asyncio.wait_for(request, 1)
    with llm_db() as db:
        assert db.get(LLMLog, "selected").error_message == LLM_CANCELLED_MESSAGE


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["custom", "anthropic", "gemini", "ollama"])
async def test_ordinary_provider_error_is_not_user_cancellation(llm_db, monkeypatch, provider_name):
    from app.services.llm.client import LLMClient
    class FailedClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("ordinary network failure")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FailedClient())
    client = LLMClient(LLMConfig(provider=provider_name, model="test", api_url="http://fake.test", api_key="fake"))
    result = await client.chat_completion("system", "user")
    assert not result["success"]
    with llm_db() as db:
        log = db.query(LLMLog).one()
        assert log.status == "error"
        assert "ordinary network failure" in log.error_message
        assert log.error_message != LLM_CANCELLED_MESSAGE


@pytest.mark.asyncio
async def test_caller_shutdown_cannot_reclassify_selected_cancellation(llm_db):
    with llm_db() as db:
        add_log(db, "selected")
    started = asyncio.Event()
    async def request():
        started.set()
        await asyncio.Event().wait()
    call = asyncio.create_task(await_cancellable_llm_request("selected", request()))
    await asyncio.wait_for(started.wait(), 1)
    with llm_db() as db:
        cancel_selected_llm_logs(LLMLogCancelRequest(ids=["selected"]), db)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    with llm_db() as db:
        log = db.get(LLMLog, "selected")
        assert log.status == "error" and log.error_message == LLM_CANCELLED_MESSAGE


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["custom", "anthropic", "gemini", "ollama"])
async def test_provider_disconnect_during_client_cleanup_ends_pending_log(llm_db, monkeypatch, provider_name):
    from app.services.llm.client import LLMClient
    closing = asyncio.Event()
    class ClosingClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            closing.set()
            await asyncio.Event().wait()
        async def post(self, *args, **kwargs):
            return SimpleNamespace(status_code=200)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: ClosingClient())
    client = LLMClient(LLMConfig(provider=provider_name, model="test", api_url="http://fake.test", api_key="fake"))
    call = asyncio.create_task(client.chat_completion("system", "user"))
    await asyncio.wait_for(closing.wait(), 1)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    with llm_db() as db:
        log = db.query(LLMLog).one()
        assert log.status == "error" and log.error_message == "LLM 请求已中断"
        result = cancel_selected_llm_logs(LLMLogCancelRequest(ids=[log.id]), db)
        assert result["data"]["cancelled_ids"] == []
