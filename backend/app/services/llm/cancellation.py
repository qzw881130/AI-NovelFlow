"""Per-log cancellation shared by all providers, including across backend workers."""
import asyncio
from contextlib import suppress
from typing import Awaitable, TypeVar

LLM_CANCELLED_MESSAGE = "任务被用户取消，LLM 响应已忽略"
POLL_INTERVAL = 0.5
T = TypeVar("T")


class LLMCallTerminated(RuntimeError):
    """Abort the business call rather than return a failure that permits fallback."""


def is_llm_log_cancelled(log_id: str) -> bool:
    from app.core.database import SessionLocal
    from app.models.llm_log import LLMLog

    with SessionLocal() as db:
        return db.query(LLMLog.id).filter(
            LLMLog.id == log_id,
            LLMLog.status == "error",
            LLMLog.error_message == LLM_CANCELLED_MESSAGE,
        ).first() is not None


async def await_cancellable_llm_request(log_id: str | None, request: Awaitable[T]) -> T:
    """Cancel only this HTTP request; never cancel a shared parent/batch task.

    The persisted flag works when the cancel endpoint and request use different
    workers. Also check after completion so a simultaneous response is discarded.
    """
    if not log_id:
        return await request
    request_task = asyncio.ensure_future(request)
    try:
        while True:
            if is_llm_log_cancelled(log_id):
                raise LLMCallTerminated(LLM_CANCELLED_MESSAGE)
            done, _ = await asyncio.wait({request_task}, timeout=POLL_INTERVAL)
            if done:
                if is_llm_log_cancelled(log_id):
                    raise LLMCallTerminated(LLM_CANCELLED_MESSAGE)
                return request_task.result()
    except asyncio.CancelledError:
        from .base import update_llm_log
        # Disconnect/shutdown ended this request, so it is no longer cancellable.
        # Keep an already committed selected cancellation if the two race.
        with suppress(LLMCallTerminated):
            update_llm_log(log_id, status="error", error_message="LLM 请求已中断")
        raise
    finally:
        if not request_task.done():
            request_task.cancel()
        # Drain cancellation/errors, including caller disconnect/shutdown.
        with suppress(asyncio.CancelledError, Exception):
            await request_task
