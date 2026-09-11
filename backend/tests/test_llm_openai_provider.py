"""OpenAI-compatible LLM provider tests."""

import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.services.llm.base import LLMConfig, build_llm_request_info
from app.services.llm.providers.openai import OpenAICompatibleProvider


V4_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp"]


def make_provider(model="deepseek-v4-flash"):
    return OpenAICompatibleProvider(
        LLMConfig(
            provider="deepseek",
            model=model,
            api_url="https://api.example.com",
            api_key="test-key",
        )
    )


def test_parse_response_reads_reasoning_content_when_content_is_empty():
    provider = make_provider()
    response_data = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": '{"shots": []}',
                }
            }
        ]
    }

    assert provider._parse_response(response_data) == '{"shots": []}'


def test_parse_response_returns_empty_string_for_empty_message():
    provider = make_provider()
    response_data = {"choices": [{"message": {"content": ""}}]}

    assert provider._parse_response(response_data) == ""


def test_get_finish_reason_reads_choice_finish_reason():
    provider = make_provider()
    response_data = {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}

    assert provider._get_finish_reason(response_data) == "length"


def test_build_llm_request_info_masks_authorization_header():
    request_info = build_llm_request_info(
        provider="deepseek",
        base_url="https://api.example.com",
        endpoint="https://api.example.com/chat/completions",
        model="deepseek-v4-flash",
        headers={"Authorization": "Bearer test-key", "Content-Type": "application/json"},
        payload={"model": "deepseek-v4-flash", "max_tokens": 4000},
        proxy_url="http://proxy.example.com",
        timeout_seconds=600,
    )

    assert request_info["headers"]["Authorization"] == "Bearer ***"
    assert request_info["payload"]["max_tokens"] == 4000


@pytest.mark.parametrize("model", V4_MODELS)
def test_deepseek_v4_json_request_disables_thinking(model):
    provider = make_provider(model)

    body = provider._build_request_body(
        system_prompt="Return JSON.",
        user_content="{}",
        temperature=0.7,
        max_tokens=4096,
        response_format="json_object",
    )

    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert body["stream"] is False


@pytest.mark.parametrize("model", V4_MODELS)
def test_deepseek_v4_text_request_does_not_force_thinking(model):
    provider = make_provider(model)

    body = provider._build_request_body(
        system_prompt="You are helpful.",
        user_content="Hi",
        temperature=0.7,
        max_tokens=4096,
        response_format=None,
    )

    assert "thinking" not in body
    assert body["stream"] is False


@pytest.mark.asyncio
async def test_deepseek_vision_preset():
    from app.api.config import get_llm_presets

    presets = await get_llm_presets()
    deepseek = next(item for item in presets["data"] if item["id"] == "deepseek")
    assert deepseek["defaultApiUrl"] == "https://api.deepseek.com"
    assert deepseek["models"][0]["id"] == "deepseek-v4-flash"
    models = {item["id"]: item for item in deepseek["models"]}
    assert models["deepseek-v4-flash-vision-exp"] == {
        "id": "deepseek-v4-flash-vision-exp",
        "name": "DeepSeek V4 Flash Vision Exp",
        "contextLength": 1048576,
        "maxTokens": 393216,
        "capabilities": {"vision": True},
    }
    for model in V4_MODELS[:2]:
        assert models[model]["maxTokens"] == 393216
        assert "capabilities" not in models[model]


@pytest.mark.parametrize("model", V4_MODELS)
@pytest.mark.parametrize("requested,expected", [(4096, 4096), (393216, 393216), (500000, 393216)])
def test_deepseek_v4_output_limit(model, requested, expected):
    from app.services.llm_service import LLMService

    service = LLMService.__new__(LLMService)
    service.model = model
    assert service._normalize_max_tokens(requested) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("model,image_url", [
    *[(model, None) for model in V4_MODELS],
    ("deepseek-v4-flash-vision-exp", "https://example.test/image.png?token=image-secret"),
    ("deepseek-v4-flash-vision-exp", "data:image/png;base64,aW1hZ2Utc2VjcmV0"),
])
async def test_deepseek_service_sends_text_and_images(db_engine, monkeypatch, capsys, model, image_url):
    from app.core import database
    from app.models.llm_log import LLMLog
    from app.services.llm_service import LLMService

    sessions = sessionmaker(bind=db_engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(
        LLM_PROVIDER="deepseek", LLM_MODEL=model,
        LLM_API_URL="https://api.deepseek.com", LLM_API_KEY="test-key",
        LLM_MAX_TOKENS=393216, LLM_TEMPERATURE=None, LLM_TIMEOUT=30,
        PROXY_ENABLED=False, HTTP_PROXY="", HTTPS_PROXY="",
    ))
    content = "Hi" if image_url is None else [
        {"type": "text", "text": "Describe this image."},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    requests = []

    def respond(request):
        requests.append(request)
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == model
        assert body["messages"] == [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": content},
        ]
        assert body["max_tokens"] == 393216
        assert "thinking" not in body
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        })

    async_client = httpx.AsyncClient
    monkeypatch.setattr("app.services.llm.providers.openai.httpx.AsyncClient", lambda **kwargs:
        async_client(transport=httpx.MockTransport(respond), timeout=kwargs["timeout"]))

    # Exercise service -> client -> provider -> JSON transport, not just body construction.
    result = await LLMService().chat_completion("You are helpful.", content)
    assert result["success"] is True
    assert result["content"] == "ok"
    assert len(requests) == 1  # Image input was not rejected before transport.
    with sessions() as db:
        log = db.query(LLMLog).one()
        assert log.status == "success"
        if image_url is None:
            assert log.user_prompt == "Hi"
        else:
            assert image_url not in log.user_prompt
            assert image_url not in log.request_info
            assert "[image omitted]" in log.user_prompt
            assert json.loads(log.user_prompt)[0]["text"] == "Describe this image."
            assert content[1]["image_url"]["url"] == image_url
    if image_url:
        assert image_url not in capsys.readouterr().out
