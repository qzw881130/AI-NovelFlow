"""LLM boundary tests: run with --noconftest, no application or database imports."""

import asyncio
import importlib
import json
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace

import httpx
import pytest


@pytest.fixture
def boundary(monkeypatch):
    # A separate package name avoids app.services' application-level imports.
    package_name = "_isolated_llm_failure_kind"
    package = ModuleType(package_name)
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "app/services/llm")]
    monkeypatch.setitem(sys.modules, package_name, package)
    base = importlib.import_module(f"{package_name}.base")
    client = importlib.import_module(f"{package_name}.client")
    logs = []

    def no_network(*args, **kwargs):
        raise AssertionError("Network access is forbidden in LLM boundary tests")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(httpx.AsyncClient, "post", no_network)
    monkeypatch.setattr(base, "update_llm_log", lambda log_id, **kwargs: logs.append(kwargs))
    for module_name in ("openai", "anthropic", "gemini", "ollama"):
        module = importlib.import_module(f"{package_name}.providers.{module_name}")
        monkeypatch.setattr(module, "create_llm_log", lambda **kwargs: "test-log")
        monkeypatch.setattr(module, "update_llm_log", base.update_llm_log)

    config = base.LLMConfig("openai", "test-model", "https://example.test/v1", "test-key")
    yield SimpleNamespace(base=base, client=client.LLMClient(config), logs=logs, config=config)
    for name in list(sys.modules):
        if name.startswith(f"{package_name}."):
            del sys.modules[name]


def test_response_defaults(boundary):
    result = boundary.base.LLMResponse(success=False)
    assert result.failure_kind is None
    assert result.diagnostic_content is None
    assert result.diagnostic_type is None


def test_log_id_propagates_to_client_result(boundary, monkeypatch):
    async def completed(**kwargs):
        return boundary.base.LLMResponse(success=True, content='{"characters":[]}', log_id="exact-log-id")
    monkeypatch.setattr(boundary.client._provider, "chat_completion", completed)
    result = asyncio.run(boundary.client.chat_completion("system", "user"))
    assert result["llm_log_id"] == "exact-log-id"


@pytest.mark.parametrize("candidate", ["", " \n\t", None, {}, {"shots": []}, [], ["prompt"], 0, 42, False])
def test_invalid_candidates_are_diagnostics_not_content(boundary, monkeypatch, candidate):
    provider = boundary.client._provider
    monkeypatch.setattr(provider, "_parse_response", lambda data: candidate)
    data = {"headers": {"Authorization": "must-not-be-logged"}, "usage": {"completion_tokens": 4}}

    result = provider._complete_response("test-log", data, 2.0)

    assert result.success is False
    assert result.failure_kind == "INVALID_OUTPUT"
    assert result.content == ""
    assert result.diagnostic_content == candidate
    assert result.diagnostic_type == type(candidate).__name__
    log = boundary.logs[0]
    assert log["status"] == "error"
    assert log["metrics"]["output_tokens_per_second"] == 2.0
    if isinstance(candidate, str) or candidate is None:
        assert log["response"] == candidate
    else:
        assert isinstance(log["response"], str)
        assert json.loads(log["response"]) == candidate
    assert "must-not-be-logged" not in json.dumps(log)


@pytest.mark.parametrize("data", [None, [], {"choices": [None]}, {"choices": [{}]}])
def test_malformed_provider_shape_is_invalid_output(boundary, data):
    result = boundary.client._provider._complete_response("test-log", data, 1.0)
    assert result.success is False
    assert result.failure_kind == "INVALID_OUTPUT"
    assert result.content == ""
    assert result.diagnostic_content is None
    assert result.diagnostic_type in {"KeyError", "TypeError", "AttributeError"}
    assert boundary.logs[0]["response"] is None


def test_parser_value_error_is_invalid_output(boundary, monkeypatch):
    def parse(data):
        return json.loads("{broken")

    monkeypatch.setattr(boundary.client._provider, "_parse_response", parse)
    result = boundary.client._provider._complete_response("test-log", {}, 1.0)
    assert result.failure_kind == "INVALID_OUTPUT"
    assert result.diagnostic_type == "JSONDecodeError"
    assert result.content == ""


@pytest.mark.parametrize("provider_name,finish_key,finish", [
    ("openai", "finish_reason", "length"),
    ("anthropic", "stop_reason", "max_tokens"),
    ("gemini", "finishReason", "MAX_TOKENS"),
])
def test_truncated_strings_are_preserved_as_diagnostics(boundary, monkeypatch, provider_name, finish_key, finish):
    boundary.config.provider = provider_name
    candidate = '{"shots": ['
    monkeypatch.setattr(boundary.client._provider, "_parse_response", lambda data: candidate)
    data = ({finish_key: finish} if provider_name == "anthropic" else
            {"candidates" if provider_name == "gemini" else "choices": [{finish_key: finish}]})

    result = boundary.client._provider._complete_response("test-log", data, 1.0)

    assert result.failure_kind == "INVALID_OUTPUT"
    assert result.content == ""
    assert result.diagnostic_content == candidate
    assert result.diagnostic_type == "str"
    assert boundary.logs[0]["response"] == candidate
    assert boundary.logs[0]["metrics"]["finish_reason"] == finish


@pytest.mark.parametrize("candidate", [
    '{"shots": [{"prompt": "A director shot"}]}',
    "x",
    "service error timeout INVALID_OUTPUT",
    "  valid text\n",
    '{"unvalidated":',
    "x" * 10000,
])
def test_valid_strings_and_metrics_are_unchanged(boundary, monkeypatch, candidate):
    data = {
        "choices": [{"message": {"content": candidate}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    }
    provider = boundary.client._provider
    response = provider._complete_response("test-log", data, 2.0)

    async def complete(**kwargs):
        return response

    monkeypatch.setattr(provider, "chat_completion", complete)
    result = asyncio.run(boundary.client.chat_completion("system", "user"))

    assert result == {
        "success": True, "content": candidate, "raw_response": data,
        "failure_kind": None, "diagnostic_content": None, "diagnostic_type": None,
        "llm_log_id": "test-log",
    }
    assert response.duration == 2.0
    log = boundary.logs[0]
    assert log["response"] == candidate
    assert log["status"] == "success"
    assert log["error_message"] is None
    assert log["metrics"]["input_tokens"] == 10
    assert log["metrics"]["output_tokens"] == 4
    assert log["metrics"]["total_tokens"] == 14
    assert log["metrics"]["output_tokens_per_second"] == 2.0


@pytest.mark.parametrize("response", [
    httpx.Response(429, json={"error": "limited", "usage": {"completion_tokens": 4}}),
    httpx.Response(503, text="unavailable"),
])
def test_http_errors_are_service_errors(boundary, response):
    result = boundary.client._provider._http_error_response("test-log", response, 2.0)
    assert result.success is False
    assert result.failure_kind == "SERVICE_ERROR"
    assert result.content == ""
    assert result.diagnostic_content is None
    assert result.diagnostic_type is None
    assert str(response.status_code) in result.error
    assert boundary.logs[0]["status"] == "error"
    if response.status_code == 429:
        assert boundary.logs[0]["metrics"]["output_tokens_per_second"] == 2.0
    else:
        assert boundary.logs[0]["metrics"] is None


@pytest.mark.parametrize("candidate", ["", None, {"shots": []}, ["prompt"], "partial"])
def test_client_propagates_invalid_output_diagnostics(boundary, monkeypatch, candidate):
    provider = boundary.client._provider
    monkeypatch.setattr(provider, "_parse_response", lambda data: candidate)
    data = {"choices": [{"finish_reason": "length"}], "headers": {"Authorization": "secret"}}
    response = provider._complete_response("test-log", data, 1.0)

    async def complete(**kwargs):
        return response

    monkeypatch.setattr(provider, "chat_completion", complete)
    result = asyncio.run(boundary.client.chat_completion("system", "user"))
    assert result["success"] is False
    assert result["failure_kind"] == "INVALID_OUTPUT"
    assert result["content"] == ""
    assert result["diagnostic_content"] == candidate
    assert result["diagnostic_type"] == type(candidate).__name__
    assert "raw_response" not in result
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("failure_kind", [None, "SERVICE_ERROR", "TIMEOUT", "UNKNOWN_ERROR"])
@pytest.mark.parametrize("candidate", ["partial", {"shots": []}, ["prompt"]])
def test_client_preserves_failed_content_without_inferring_error_kind(boundary, monkeypatch, failure_kind, candidate):
    async def complete(**kwargs):
        return boundary.base.LLMResponse(
            success=False, content=candidate, error="[ReadTimeout] API error (503)",
            failure_kind=failure_kind, raw_response={"headers": {"Authorization": "secret"}},
        )

    monkeypatch.setattr(boundary.client._provider, "chat_completion", complete)
    result = asyncio.run(boundary.client.chat_completion("system", "user"))
    assert result["failure_kind"] == (failure_kind or "UNKNOWN_ERROR")
    assert result["content"] == ""
    assert result["diagnostic_content"] == candidate
    assert result["diagnostic_type"] == type(candidate).__name__
    assert "raw_response" not in result


@pytest.mark.parametrize("exception,expected", [
    (httpx.ReadTimeout("known timeout"), "TIMEOUT"),
    (TimeoutError("known timeout"), "TIMEOUT"),
    (httpx.HTTPStatusError("HTTP failure", request=httpx.Request("POST", "https://example.test"),
                           response=httpx.Response(503)), "SERVICE_ERROR"),
    (httpx.ConnectError("connection failed"), "SERVICE_ERROR"),
    (RuntimeError("timeout API error (503)"), "UNKNOWN_ERROR"),
])
def test_client_classifies_typed_exceptions_without_retries(boundary, monkeypatch, exception, expected):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        raise exception

    monkeypatch.setattr(boundary.client._provider, "chat_completion", complete)
    result = asyncio.run(boundary.client.chat_completion("system", "user"))
    assert result["success"] is False
    assert result["failure_kind"] == expected
    assert result["content"] == ""
    assert result["diagnostic_content"] is None
    assert result["diagnostic_type"] is None
    assert len(calls) == 1


def test_client_does_not_swallow_cancellation(boundary, monkeypatch):
    async def complete(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(boundary.client._provider, "chat_completion", complete)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(boundary.client.chat_completion("system", "user"))


@pytest.fixture(params=["openai", "anthropic", "gemini", "ollama", "deepseek", "aliyun-bailian"])
def real_provider(boundary, monkeypatch, request):
    outcomes = []
    requests = []
    pending_logs = []
    config = boundary.base.LLMConfig(
        request.param, "test-model", "https://example.test/v1",
        "first-private-api-key,second-private-api-key",
    )
    client = type(boundary.client)(config)
    module = sys.modules[type(client._provider).__module__]
    monkeypatch.setattr(module, "create_llm_log", lambda **kwargs: pending_logs.append(kwargs) or "test-log")
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 100.0 + len(requests) * 2))
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(key, raising=False)

    class FakeHTTPClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, endpoint, **kwargs):
            requests.append(kwargs)
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    monkeypatch.setattr(httpx, "AsyncClient", FakeHTTPClient)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: None)
    return SimpleNamespace(
        client=client, provider=client._provider, outcomes=outcomes, requests=requests,
        pending_logs=pending_logs, logs=boundary.logs, name=request.param,
    )


@pytest.mark.parametrize("body", [b"", b"{broken JSON", b"\xff"])
def test_real_provider_malformed_http_200_preserves_body(real_provider, body):
    request = httpx.Request("POST", "https://example.test", headers={"Authorization": "request-secret"})
    response = httpx.Response(200, content=body, request=request, headers={"x-api-key": "response-secret"})
    real_provider.outcomes.extend([response, response])

    internal = asyncio.run(real_provider.provider.chat_completion("system", "user"))
    result = asyncio.run(real_provider.client.chat_completion("system", "user"))

    assert internal.success is False
    assert internal.failure_kind == result["failure_kind"] == "INVALID_OUTPUT"
    assert internal.content == result["content"] == ""
    assert internal.diagnostic_content == result["diagnostic_content"] == response.text
    assert internal.diagnostic_type == result["diagnostic_type"] == "str"
    assert internal.raw_response is None
    assert "raw_response" not in result
    assert len(real_provider.requests) == len(real_provider.logs) == 2
    for log in real_provider.logs:
        assert log["response"] == response.text
        assert log["status"] == "error"
        assert log["duration"] == 2.0
    serialized = json.dumps([result, real_provider.logs, real_provider.pending_logs])
    for secret in ("request-secret", "response-secret", "first-private-api-key", "second-private-api-key"):
        assert secret not in serialized


@pytest.mark.parametrize("exception,expected", [
    (httpx.ReadTimeout("known timeout"), "TIMEOUT"),
    (TimeoutError("known timeout"), "TIMEOUT"),
    (httpx.ConnectError("connection failed"), "SERVICE_ERROR"),
    (httpx.RemoteProtocolError("broken response"), "SERVICE_ERROR"),
    (ConnectionError("connection reset"), "SERVICE_ERROR"),
    (httpx.HTTPStatusError("HTTP failure", request=httpx.Request("POST", "https://example.test"),
                           response=httpx.Response(503)), "SERVICE_ERROR"),
    (json.JSONDecodeError("no HTTP response", "", 0), "UNKNOWN_ERROR"),
    (RuntimeError("timeout API error (503)"), "UNKNOWN_ERROR"),
])
def test_real_provider_classifies_transport_exceptions(real_provider, exception, expected):
    real_provider.outcomes.extend([exception, exception])

    internal = asyncio.run(real_provider.provider.chat_completion("system", "user"))
    result = asyncio.run(real_provider.client.chat_completion("system", "user"))

    assert internal.success is False
    assert internal.failure_kind == result["failure_kind"] == expected
    assert internal.content == result["content"] == ""
    assert internal.diagnostic_content is result["diagnostic_content"] is None
    assert internal.diagnostic_type is result["diagnostic_type"] is None
    assert len(real_provider.requests) == len(real_provider.logs) == 2
    for log in real_provider.logs:
        assert log["status"] == "error"
        assert log["response"] is None
        assert log["duration"] == 2.0


def test_real_provider_context_is_local_and_key_rotation_is_unchanged(real_provider):
    real_provider.outcomes.extend([httpx.Response(200, text="{previous body"), httpx.ReadTimeout("timeout")])
    first = asyncio.run(real_provider.provider.chat_completion("system", "user"))
    second = asyncio.run(real_provider.provider.chat_completion("system", "user"))

    assert first.failure_kind == "INVALID_OUTPUT"
    assert second.failure_kind == "TIMEOUT"
    assert second.diagnostic_content is None
    assert len(real_provider.requests) == len(real_provider.logs) == 2
    assert real_provider.logs[-1]["response"] is None
    headers = [call["headers"] for call in real_provider.requests]
    if real_provider.name == "ollama":
        assert headers[0] == headers[1]
    else:
        assert "first-private-api-key" in headers[0].values() or "Bearer first-private-api-key" in headers[0].values()
        assert "second-private-api-key" in headers[1].values() or "Bearer second-private-api-key" in headers[1].values()


def test_real_provider_redacts_reflected_api_keys(real_provider, capsys):
    real_provider.outcomes.extend([
        httpx.Response(200, text="{invalid first-private-api-key second-private-api-key"),
        httpx.ConnectError("failed first-private-api-key second-private-api-key"),
    ])
    invalid = asyncio.run(real_provider.client.chat_completion("system", "user"))
    failed = asyncio.run(real_provider.client.chat_completion("system", "user"))

    assert invalid["diagnostic_content"] == "{invalid *** ***"
    serialized = json.dumps([invalid, failed, real_provider.logs, real_provider.pending_logs]) + capsys.readouterr().out
    assert "first-private-api-key" not in serialized
    assert "second-private-api-key" not in serialized


@pytest.mark.parametrize("via_client", [False, True])
def test_real_provider_cancellation_still_propagates(real_provider, via_client):
    real_provider.outcomes.append(asyncio.CancelledError())
    caller = real_provider.client if via_client else real_provider.provider
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(caller.chat_completion("system", "user"))
    assert len(real_provider.requests) == 1
    if real_provider.name in {"openai", "deepseek", "aliyun-bailian"}:
        assert real_provider.logs[0]["status"] == "error"
    else:
        assert real_provider.logs == []
