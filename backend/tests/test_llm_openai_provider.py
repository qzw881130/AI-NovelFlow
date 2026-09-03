"""OpenAI-compatible LLM provider tests."""

from app.services.llm.base import LLMConfig, build_llm_request_info
from app.services.llm.providers.openai import OpenAICompatibleProvider


def make_provider():
    return OpenAICompatibleProvider(
        LLMConfig(
            provider="deepseek",
            model="deepseek-v4-flash",
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


def test_deepseek_v4_json_request_disables_thinking():
    provider = make_provider()

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


def test_deepseek_v4_text_request_does_not_force_thinking():
    provider = make_provider()

    body = provider._build_request_body(
        system_prompt="You are helpful.",
        user_content="Hi",
        temperature=0.7,
        max_tokens=4096,
        response_format=None,
    )

    assert "thinking" not in body
    assert body["stream"] is False
