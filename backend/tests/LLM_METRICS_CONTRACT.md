# LLM Log Metrics

Both `GET /api/llm-logs/` list items and `GET /api/llm-logs/{id}` detail
objects expose `metrics`. Existing `duration` remains request elapsed seconds.
Persistence uses nullable JSON `llm_logs.usage_metrics`, added idempotently by
the existing startup SQLite upgrade. Historical rows are not backfilled.

`metrics` is null for historical/pending logs and failures without a parsed
provider response. Otherwise it contains these nullable fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `input_tokens` | integer | Provider-reported input/prompt count |
| `output_tokens` | integer | Provider-reported output/completion count |
| `total_tokens` | integer | Provider-reported total, never synthesized |
| `cached_input_tokens` | integer | Cache-read/hit input tokens, not cache writes or a hit rate |
| `reasoning_tokens` | integer | Explicit reasoning/thought token count |
| `finish_reason` | string | Unmodified provider reason, suitable for a tooltip |
| `output_tokens_per_second` | number | Output tokens divided by total request seconds |
| `raw_usage` | object | Numeric provider usage metadata, including nested numeric details |

Zero is a real value; null means unknown. Throughput is null if output count
is unknown or duration is nonpositive/unknown. Label it "Average output tokens/s"
with a tooltip such as "Output tokens / total request duration; not generation
speed." Do not substitute Ollama's `eval_duration` for the denominator.

OpenAI-compatible adapters (including DeepSeek and Ollama) read `usage` and
the first choice's `finish_reason`. DeepSeek also supports
`prompt_cache_hit_tokens`. Ollama native counters are recognized if returned,
but the adapter continues to request the OpenAI-compatible endpoint.
Anthropic reads `usage` and `stop_reason`: its `input_tokens` excludes cache
reads/writes, which remain in cache/read and raw fields; absent totals stay null.
Gemini reads `usageMetadata` and the first candidate's `finishReason`;
`candidatesTokenCount` is not augmented with `thoughtsTokenCount`.

Empty, malformed, length-limited, and HTTP error responses retain reported
usage. Raw usage is deliberately restricted to numeric metadata so arbitrary
response strings or credentials are not copied into this field.
