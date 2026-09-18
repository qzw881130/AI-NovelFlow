"""Usage capture uses mocked HTTP and isolated SQLite, never the live database."""
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.core import database
from app.models.llm_log import LLMLog
from app.services.llm.base import LLMConfig, build_llm_request_info
from app.services.llm.metrics import normalize_metrics
from app.services.sqlite_schema_upgrade import upgrade_sqlite_schema


CASES = [
    ("openai", "openai", "OpenAICompatibleProvider"),
    ("deepseek", "openai", "OpenAICompatibleProvider"),
    ("anthropic", "anthropic", "AnthropicProvider"),
    ("gemini", "gemini", "GeminiProvider"),
    ("ollama", "ollama", "OllamaProvider"),
]


def response_data(provider, content="ok", length=False):
    if provider == "anthropic":
        return {
            "content": [{"type": "text", "text": content}],
            "stop_reason": "max_tokens" if length else "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 4,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 3},
        }
    if provider == "gemini":
        return {
            "candidates": [{"content": {"parts": [{"text": content}]},
                            "finishReason": "MAX_TOKENS" if length else "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4,
                              "totalTokenCount": 16, "cachedContentTokenCount": 0,
                              "thoughtsTokenCount": 2},
        }
    usage = {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
             "completion_tokens_details": {"reasoning_tokens": 2}}
    if provider == "deepseek":
        usage["prompt_cache_hit_tokens"] = 0
    else:
        usage["prompt_tokens_details"] = {"cached_tokens": 0}
    return {"choices": [{"message": {"content": content},
                         "finish_reason": "length" if length else "stop"}], "usage": usage}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,module_name,class_name", CASES)
@pytest.mark.parametrize("outcome", ["success", "length", "empty", "missing", "timeout", "http_error", "http_error_no_usage", "malformed"])
async def test_provider_metrics_persist(db_engine, monkeypatch, provider, module_name, class_name, outcome):
    sessions = sessionmaker(bind=db_engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    module = importlib.import_module(f"app.services.llm.providers.{module_name}")
    times = iter([100.0, 102.0])
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: next(times)))
    data = response_data(provider, "" if outcome == "empty" else "ok", outcome == "length")
    if outcome == "missing":
        data.pop("usageMetadata" if provider == "gemini" else "usage")
    if outcome == "malformed":
        data["content" if provider == "anthropic" else "candidates" if provider == "gemini" else "choices"] = [{}]

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, endpoint, **kwargs):
            if outcome == "timeout":
                raise httpx.ReadTimeout("mock timeout")
            if outcome == "http_error_no_usage":
                return httpx.Response(503, text="Service unavailable")
            return httpx.Response(503 if outcome == "http_error" else 200, json=data)

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeClient)
    adapter = getattr(module, class_name)(LLMConfig(provider, "test-model", "https://example.test/v1", "secret-key"))
    result = await adapter.chat_completion("system", "user")
    assert result.success == (outcome in {"success", "missing"})
    with sessions() as db:
        log = db.query(LLMLog).one()
        assert log.status == ("success" if result.success else "error")
        assert log.duration == 2.0
        assert "secret-key" not in log.request_info
        if outcome in {"timeout", "http_error_no_usage"}:
            assert log.usage_metrics is None
            return
        metrics = log.usage_metrics
        assert set(metrics) == {"input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
                                "reasoning_tokens", "finish_reason", "output_tokens_per_second", "raw_usage"}
        if outcome == "missing":
            assert metrics["input_tokens"] is None
            assert metrics["output_tokens_per_second"] is None
            assert metrics["raw_usage"] is None
        else:
            assert metrics["input_tokens"] == 10
            assert metrics["output_tokens"] == 4
            assert metrics["cached_input_tokens"] == 0
            assert metrics["output_tokens_per_second"] == 2.0
            assert metrics["total_tokens"] == (None if provider == "anthropic" else 16 if provider == "gemini" else 14)
            assert metrics["raw_usage"] == data.get("usage", data.get("usageMetadata"))
        if outcome == "length":
            assert metrics["finish_reason"] in {"length", "max_tokens", "MAX_TOKENS"}


@pytest.mark.parametrize("duration,expected", [(2, 0.0), (0, None), (-1, None), (None, None)])
def test_zero_and_unknown_counters(duration, expected):
    metrics = normalize_metrics("openai", {"usage": {"completion_tokens": 0}}, duration)
    assert metrics["output_tokens"] == 0
    assert metrics["output_tokens_per_second"] == expected
    assert metrics["input_tokens"] is None
    assert metrics["total_tokens"] is None
    assert metrics["cached_input_tokens"] is None


def test_ollama_native_usage_and_safe_raw_metadata():
    metrics = normalize_metrics("ollama", {
        "prompt_eval_count": 10, "eval_count": 4, "eval_duration": 100,
        "done_reason": "stop", "message": {"content": "not usage"},
    }, 2)
    assert metrics["output_tokens_per_second"] == 2
    assert metrics["total_tokens"] is None
    assert metrics["finish_reason"] == "stop"
    assert "message" not in metrics["raw_usage"]
    metrics = normalize_metrics("openai", {"usage": {
        "completion_tokens": 0, "api_key": "secret", "secret": 123,
        "details": {"authorization": "secret", "tokens": 0},
    }}, 2)
    assert metrics["raw_usage"] == {"completion_tokens": 0, "details": {"tokens": 0}}


def test_request_urls_and_google_headers_are_redacted():
    info = build_llm_request_info(
        "gemini", "https://user:password@example.test?key=secret", "https://example.test?key=secret",
        "test", {"x-goog-api-key": "secret"}, {}, "http://user:password@proxy.test",
    )
    assert "secret" not in json.dumps(info)
    assert "password" not in json.dumps(info)


def test_sqlite_upgrade_is_idempotent_and_preserves_old_rows():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE llm_logs (id VARCHAR PRIMARY KEY, response TEXT, created_at DATETIME, status VARCHAR)"))
        conn.execute(text("INSERT INTO llm_logs (id, response) VALUES ('old', 'keep')"))
        conn.execute(text("CREATE TABLE novels (id VARCHAR PRIMARY KEY, title VARCHAR NOT NULL)"))
        conn.execute(text("INSERT INTO novels (id, title) VALUES ('old-novel', 'keep novel')"))
    upgrade_sqlite_schema(engine)
    upgrade_sqlite_schema(engine)
    assert [column["name"] for column in inspect(engine).get_columns("llm_logs")].count("usage_metrics") == 1
    assert [column["name"] for column in inspect(engine).get_columns("llm_logs")].count("execution_metadata") == 1
    assert [column["name"] for column in inspect(engine).get_columns("novels")].count("shot_contract_repair_prompt_template_id") == 1
    indexes = {index["name"]: index["column_names"] for index in inspect(engine).get_indexes("llm_logs")}
    assert indexes["ix_llm_logs_created_at_id"] == ["created_at", "id"]
    assert indexes["ix_llm_logs_status_created_at"] == ["status", "created_at"]
    with engine.begin() as conn:
        assert conn.execute(text("SELECT response, usage_metrics, duration, execution_metadata FROM llm_logs")).one() == ("keep", None, None, None)
        assert conn.execute(text("SELECT title, shot_contract_repair_prompt_template_id FROM novels")).one() == ("keep novel", None)
    engine.dispose()


def test_list_and_detail_api_metrics(db_session):
    from app.api.llm_logs import router
    app = FastAPI()
    app.include_router(router, prefix="/logs")
    app.dependency_overrides[database.get_db] = lambda: db_session
    metrics = normalize_metrics("openai", response_data("openai"), 2)
    db_session.add_all([
        LLMLog(id="new", provider="openai", model="test", user_prompt="user", status="success",
               duration=2, usage_metrics=metrics,execution_metadata={"outcome":"REPAIRED"}),
        LLMLog(id="old", provider="openai", model="test", user_prompt="user", status="success"),
    ])
    db_session.commit()
    with TestClient(app) as client:
        items = client.get("/logs/").json()["data"]["items"]
        assert {item["id"]: item["metrics"] for item in items} == {"new": metrics, "old": None}
        assert client.get("/logs/new").json()["data"]["metrics"] == metrics
        assert client.get("/logs/new").json()["data"]["execution_metadata"] == {"outcome":"REPAIRED"}
        assert client.get("/logs/old").json()["data"]["metrics"] is None
