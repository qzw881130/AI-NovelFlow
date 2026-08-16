"""OpenAI-compatible LLM provider tests."""

from app.services.llm.base import LLMConfig
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
