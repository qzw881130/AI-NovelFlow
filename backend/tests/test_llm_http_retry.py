"""Transient LLM HTTP retries use one immutable request and one existing log."""
import copy
import json

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.core import database
from app.models.llm_log import LLMLog
from app.services.llm import http_retry
from app.services.llm.base import LLMConfig
from app.services.llm.client import LLMClient
from app.services.llm.cancellation import LLMCallTerminated
from app.services.llm import cancellation
from app.api.llm_logs import LLMLogCancelRequest, cancel_selected_llm_logs
from app.services.video_director_ai import _canonical_visual_body_speech_issues


@pytest.fixture
def llm_db(db_engine, monkeypatch):
    factory = sessionmaker(bind=db_engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    return factory


class FakeClient:
    def __init__(self, statuses, provider):
        self.statuses = list(statuses)
        self.provider = provider
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, endpoint, *, headers, json, timeout):
        self.calls.append((endpoint, copy.deepcopy(headers), copy.deepcopy(json), timeout))
        status = self.statuses.pop(0)
        content = {
            "anthropic": {"content": [{"text": "人物发声"}]},
            "gemini": {"candidates": [{"content": {"parts": [{"text": "人物发声"}]}}]},
        }.get(self.provider, {"choices": [{"message": {"content": "人物发声"}}]})
        return httpx.Response(status, json=content if status == 200 else {"error": "upstream"},
                              request=httpx.Request("POST", endpoint))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statuses,expected_delays,expected_outcome,success",
    [
        ([502, 200], [2], "recovered", True),
        ([503, 503, 200], [2, 5], "recovered", True),
        ([504, 504, 504, 504], [2, 5, 10], "exhausted", False),
        ([429, 200], [2], "recovered", True),
        ([400], [], "non_retryable", False),
        ([401], [], "non_retryable", False),
        ([403], [], "non_retryable", False),
        ([500], [], "non_retryable", False),
    ],
)
async def test_transient_http_statuses_and_request_invariance(
    statuses, expected_delays, expected_outcome, success, llm_db, monkeypatch,
):
    fake = FakeClient(statuses, "custom")
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)
    monkeypatch.setattr(http_retry.asyncio, "sleep", fake_sleep)
    client = LLMClient(LLMConfig(provider="custom", model="fixed-model", api_url="http://llm.test/v1",
                                 api_key="fixed-key", timeout=3))
    result = await client.chat_completion("fixed system", "fixed user", temperature=0.42,
                                          max_tokens=123, response_format="json_object")

    assert result["success"] is success
    assert len(fake.calls) == len(statuses)
    assert delays == expected_delays
    assert all(call == fake.calls[0] for call in fake.calls)
    endpoint, headers, body, timeout = fake.calls[0]
    assert endpoint == "http://llm.test/v1/chat/completions"
    assert headers["Authorization"] == "Bearer fixed-key"
    assert body["model"] == "fixed-model"
    assert body["messages"] == [{"role": "system", "content": "fixed system"},
                                {"role": "user", "content": "fixed user"}]
    assert body["temperature"] == 0.42 and body["max_tokens"] == 123
    assert body["response_format"] == {"type": "json_object"}
    assert timeout == 3
    with llm_db() as db:
        log = db.query(LLMLog).one()
        retry = json.loads(log.request_info)["httpRetry"]
        assert [item["attempt"] for item in retry["attempts"]] == list(range(1, len(statuses) + 1))
        assert [item["httpStatus"] for item in retry["attempts"]] == statuses
        assert retry["transientRetryOccurred"] is (len(statuses) > 1)
        assert retry["outcome"] == expected_outcome
        assert log.status == ("success" if success else "error")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["custom", "anthropic", "gemini", "ollama"])
async def test_each_provider_uses_shared_http_retry(provider, llm_db, monkeypatch):
    fake = FakeClient([502, 200], provider)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)

    async def fake_sleep(_):
        return None

    monkeypatch.setattr(http_retry.asyncio, "sleep", fake_sleep)
    client = LLMClient(LLMConfig(provider=provider, model="fixed-model", api_url="http://llm.test/v1",
                                 api_key="fixed-key"))
    result = await client.chat_completion("system", "user")
    assert result["success"] is True
    assert len(fake.calls) == 2
    assert fake.calls[0] == fake.calls[1]


@pytest.mark.asyncio
async def test_business_validation_failure_does_not_retry_http(llm_db, monkeypatch):
    fake = FakeClient([200], "custom")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)
    client = LLMClient(LLMConfig(provider="custom", model="fixed-model", api_url="http://llm.test/v1",
                                 api_key="fixed-key"))
    result = await client.chat_completion("system", "user")

    assert result["success"] is True
    assert _canonical_visual_body_speech_issues(result["content"]) == [
        "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"
    ]
    assert len(fake.calls) == 1
    with llm_db() as db:
        retry = json.loads(db.query(LLMLog).one().request_info)["httpRetry"]
        assert retry["outcome"] == "success"
        assert retry["transientRetryOccurred"] is False


@pytest.mark.asyncio
async def test_malformed_success_response_does_not_retry_http(llm_db, monkeypatch):
    fake = FakeClient([200], "custom")

    async def malformed_post(endpoint, *, headers, json, timeout):
        fake.calls.append((endpoint, copy.deepcopy(headers), copy.deepcopy(json), timeout))
        return httpx.Response(200, content=b"{broken", request=httpx.Request("POST", endpoint))

    fake.post = malformed_post
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)
    client = LLMClient(LLMConfig(provider="custom", model="fixed-model", api_url="http://llm.test/v1",
                                 api_key="fixed-key"))
    result = await client.chat_completion("system", "user")
    assert result["success"] is False
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_selected_cancellation_during_backoff_prevents_second_request(llm_db, monkeypatch):
    import asyncio

    fake = FakeClient([502, 200], "custom")
    entered_backoff = asyncio.Event()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)
    monkeypatch.setattr(cancellation, "POLL_INTERVAL", 0.01)

    async def pending_sleep(_):
        entered_backoff.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(http_retry.asyncio, "sleep", pending_sleep)
    client = LLMClient(LLMConfig(provider="custom", model="fixed-model", api_url="http://llm.test/v1",
                                 api_key="fixed-key"))
    call = asyncio.create_task(client.chat_completion("system", "user"))
    await asyncio.wait_for(entered_backoff.wait(), 1)
    with llm_db() as db:
        log_id = db.query(LLMLog).one().id
        cancel_selected_llm_logs(LLMLogCancelRequest(ids=[log_id]), db)
    with pytest.raises(LLMCallTerminated):
        await asyncio.wait_for(call, 1)
    assert len(fake.calls) == 1
    with llm_db() as db:
        retry = json.loads(db.query(LLMLog).one().request_info)["httpRetry"]
        assert retry["transientRetryOccurred"] is False
