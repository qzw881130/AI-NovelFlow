from app.services.llm.metrics import normalize_metrics


def test_normalize_openai_usage_and_speed():
    metrics = normalize_metrics("openai", {
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "total_tokens": 140,
            "prompt_tokens_details": {"cached_tokens": 20},
            "completion_tokens_details": {"reasoning_tokens": 5},
        },
        "choices": [{"finish_reason": "stop"}],
    }, 2.0)

    assert metrics["input_tokens"] == 100
    assert metrics["output_tokens"] == 40
    assert metrics["total_tokens"] == 140
    assert metrics["cached_input_tokens"] == 20
    assert metrics["reasoning_tokens"] == 5
    assert metrics["finish_reason"] == "stop"
    assert metrics["output_tokens_per_second"] == 20.0


def test_normalize_gemini_and_ollama_usage():
    gemini = normalize_metrics("gemini", {
        "usageMetadata": {
            "promptTokenCount": 12,
            "candidatesTokenCount": 8,
            "totalTokenCount": 20,
        },
        "candidates": [{"finishReason": "STOP"}],
    }, 4.0)
    ollama = normalize_metrics("ollama", {
        "prompt_eval_count": 30,
        "eval_count": 10,
        "done_reason": "stop",
    }, 2.0)

    assert gemini["output_tokens_per_second"] == 2.0
    assert gemini["finish_reason"] == "STOP"
    assert ollama["input_tokens"] == 30
    assert ollama["output_tokens"] == 10
    assert ollama["total_tokens"] == 40
    assert ollama["output_tokens_per_second"] == 5.0
