"""Bounded retry for transient LLM HTTP responses only."""
import asyncio

from .base import record_llm_http_attempt
from .cancellation import await_cancellable_llm_request


RETRYABLE_HTTP_STATUSES = frozenset({429, 502, 503, 504})
RETRY_DELAYS = (2, 5, 10)
MAX_REQUEST_ATTEMPTS = 1 + len(RETRY_DELAYS)


async def post_llm_request(client, log_id, endpoint, *, headers, body, timeout):
    """Resend the same HTTP request only when its response status is transient."""
    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        response = await await_cancellable_llm_request(
            log_id,
            client.post(endpoint, headers=headers, json=body, timeout=timeout),
        )
        retryable = response.status_code in RETRYABLE_HTTP_STATUSES
        will_retry = retryable and attempt < MAX_REQUEST_ATTEMPTS
        if will_retry:
            outcome = "retrying"
        elif response.status_code == 200:
            outcome = "recovered" if attempt > 1 else "success"
        elif retryable:
            outcome = "exhausted"
        else:
            outcome = "non_retryable"
        record_llm_http_attempt(
            log_id,
            attempt=attempt,
            http_status=response.status_code,
            will_retry=will_retry,
            outcome=outcome,
        )
        if not will_retry:
            return response
        await await_cancellable_llm_request(log_id, asyncio.sleep(RETRY_DELAYS[attempt - 1]))
