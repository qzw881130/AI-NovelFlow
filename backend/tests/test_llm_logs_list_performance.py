"""List-query regressions without network calls or timing-sensitive assertions."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.api import llm_logs
from app.core.database import get_db
from app.models.llm_log import LLMLog


def test_stale_reconcile_is_conditional_and_does_not_load_logs(db_session, monkeypatch):
    now = datetime(2026, 9, 9, 12)
    monkeypatch.setattr(llm_logs, "datetime", SimpleNamespace(utcnow=lambda: now))
    monkeypatch.setattr(llm_logs, "get_settings", lambda: SimpleNamespace(LLM_TIMEOUT=300))
    cutoff = now - timedelta(seconds=360)
    for log_id, status, created_at in [
        ("stale", "pending", cutoff - timedelta(seconds=1)),
        ("boundary", "pending", cutoff),
        ("recent", "pending", now),
        ("success", "success", cutoff - timedelta(hours=1)),
        ("error", "error", cutoff - timedelta(hours=1)),
    ]:
        db_session.add(LLMLog(
            id=log_id, provider="deepseek", model="test", status=status,
            created_at=created_at, user_prompt="large prompt" * 10000,
            request_info="large request" * 10000, response="keep",
        ))
    db_session.commit()
    db_session.expunge_all()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        assert llm_logs.reconcile_stale_pending_llm_logs(db_session) == 1
        assert not db_session.identity_map
        selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
        assert len(selects) == 1
        assert "EXISTS" in selects[0].upper()
        assert "user_prompt" not in selects[0]
        updates = [sql for sql in statements if sql.lstrip().upper().startswith("UPDATE")]
        assert len(updates) == 1
        assert "llm_logs.status =" in updates[0].split("WHERE")[1]
        assert "llm_logs.created_at <" in updates[0].split("WHERE")[1]

        statements.clear()
        assert llm_logs.reconcile_stale_pending_llm_logs(db_session) == 0
        assert len(statements) == 1
        assert statements[0].lstrip().upper().startswith("SELECT")
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)

    logs = {log.id: log for log in db_session.query(LLMLog).all()}
    assert {key: log.status for key, log in logs.items()} == {
        "stale": "error", "boundary": "pending", "recent": "pending",
        "success": "success", "error": "error",
    }
    assert logs["stale"].error_message
    assert all(log.response == "keep" for log in logs.values())


def test_log_queries_use_indexes(db_engine):
    with db_engine.connect() as conn:
        page_plan = " ".join(row[3] for row in conn.execute(text(
            "EXPLAIN QUERY PLAN SELECT id, created_at, substr(user_prompt, 1, 500) "
            "FROM llm_logs ORDER BY created_at DESC, id DESC LIMIT 20"
        )))
        stale_plan = " ".join(row[3] for row in conn.execute(text(
            "EXPLAIN QUERY PLAN SELECT EXISTS (SELECT 1 FROM llm_logs "
            "WHERE status = 'pending' AND created_at < '2026-09-09')"
        )))
    assert "ix_llm_logs_created_at_id" in page_plan
    assert "TEMP B-TREE" not in page_plan
    assert "SEARCH llm_logs USING COVERING INDEX ix_llm_logs_status_created_at" in stale_plan


def test_summary_pagination_filters_and_full_detail_are_preserved(db_session):
    for log_id, provider in [("a", "deepseek"), ("b", "deepseek"), ("c", "openai")]:
        db_session.add(LLMLog(
            id=log_id, provider=provider, model="test", status="success",
            created_at=datetime(2026, 9, 9), user_prompt="p" * 1000,
            system_prompt="system", request_info="request", response="response",
            usage_metrics={"output_tokens": 0},
        ))
    db_session.commit()
    app = FastAPI()
    app.include_router(llm_logs.router, prefix="/logs")
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as client:
        pages = [client.get("/logs/", params={
            "page": page, "page_size": 1, "provider": "deepseek", "status": "success",
        }).json()["data"] for page in (1, 2)]
        assert [page["items"][0]["id"] for page in pages] == ["b", "a"]
        assert pages[0]["pagination"] == {"page": 1, "page_size": 1, "total": 2, "total_pages": 2}
        for page in pages:
            item = page["items"][0]
            assert item["user_prompt"] == "p" * 500
            assert item["system_prompt"] == item["request_info"] == item["response"] == ""
            assert item["metrics"] == {"output_tokens": 0}
        detail = client.get("/logs/b").json()["data"]
        assert detail["user_prompt"] == "p" * 1000
        assert detail["system_prompt"] == "system"
        assert detail["request_info"] == "request"
        assert detail["response"] == "response"
