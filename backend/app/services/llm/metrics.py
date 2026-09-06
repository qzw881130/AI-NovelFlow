"""Provider-reported counters only; missing values are never estimated."""
import math


def normalize_metrics(provider, data, duration):
    def count(value):
        return value if type(value) is int and value >= 0 else None

    def mapping(value):
        return value if isinstance(value, dict) else {}

    # Retain numeric usage metadata, not arbitrary strings or response content.
    def numeric_usage(value):
        result = {}
        for key, item in value.items():
            if any(secret in key.lower() for secret in ("key", "secret", "authorization", "password")):
                continue
            if type(item) in (int, float) and math.isfinite(item):
                result[key] = item
            elif isinstance(item, dict):
                nested = numeric_usage(item)
                if nested:
                    result[key] = nested
        return result

    data = mapping(data)
    usage = mapping(data.get("usageMetadata" if provider == "gemini" else "usage"))
    choices = data.get("candidates" if provider == "gemini" else "choices")
    choice = mapping(choices[0]) if isinstance(choices, list) and choices else {}
    if provider == "anthropic":
        input_tokens = count(usage.get("input_tokens"))
        output_tokens = count(usage.get("output_tokens"))
        cached = count(usage.get("cache_read_input_tokens"))
        reasoning = None
        finish = data.get("stop_reason")
    elif provider == "gemini":
        input_tokens = count(usage.get("promptTokenCount"))
        output_tokens = count(usage.get("candidatesTokenCount"))
        cached = count(usage.get("cachedContentTokenCount"))
        reasoning = count(usage.get("thoughtsTokenCount"))
        finish = choice.get("finishReason")
    else:
        input_tokens = count(usage.get("prompt_tokens"))
        output_tokens = count(usage.get("completion_tokens"))
        cached = count(mapping(usage.get("prompt_tokens_details")).get("cached_tokens"))
        if cached is None:
            cached = count(usage.get("prompt_cache_hit_tokens"))
        reasoning = count(mapping(usage.get("completion_tokens_details")).get("reasoning_tokens"))
        finish = choice.get("finish_reason")
        if provider == "ollama" and not usage:
            usage = {key: data[key] for key in (
                "prompt_eval_count", "eval_count", "total_duration", "load_duration",
                "prompt_eval_duration", "eval_duration",
            ) if key in data}
            input_tokens = count(usage.get("prompt_eval_count"))
            output_tokens = count(usage.get("eval_count"))
            finish = data.get("done_reason")

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": count(usage.get("totalTokenCount" if provider == "gemini" else "total_tokens")),
        "cached_input_tokens": cached,
        "reasoning_tokens": reasoning,
        "finish_reason": finish if isinstance(finish, str) else None,
        # End-to-end average, NOT the provider's decoding/generation speed.
        "output_tokens_per_second": output_tokens / duration
        if output_tokens is not None and duration is not None and math.isfinite(duration) and duration > 0 else None,
        "raw_usage": numeric_usage(usage) if usage else None,
    }
