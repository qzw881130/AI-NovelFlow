"""Publish one result event for each novel parsing request."""
from functools import wraps
from inspect import signature
import logging

from app.services.business_events import publish

logger = logging.getLogger(__name__)


def publish_parse_result(flow: str, novel_id: str, result=None, *, chapter=None, failed=False):
    success = not failed and isinstance(result, dict) and result.get("success") is True
    statistics = result.get("statistics") if isinstance(result, dict) else None
    statistics = statistics if isinstance(statistics, dict) else {}
    details = {f"{key}_count": statistics[key] for key in ("created", "updated", "deleted")
               if isinstance(statistics.get(key), int) and not isinstance(statistics[key], bool)}
    if chapter is not None:
        details["chapter_number"] = getattr(chapter, "number", None)
    try:
        publish(f"{flow}.{'completed' if success else 'failed'}", {
            "novel_id": novel_id,
            "chapter_id": getattr(chapter, "id", None) if chapter is not None else None,
            "source": f"novel.{flow}",
            "details": details,
        })
    except Exception:
        logger.exception("Parse result retained; event persistence failed: %s", flow)


def observed_parse(flow: str):
    """Observe service results so novel and chapter routes share the same event path."""
    def decorate(fn):
        parameters = signature(fn)

        @wraps(fn)
        async def wrapper(*args, **kwargs):
            values = parameters.bind(*args, **kwargs).arguments
            novel_id = values["novel_id"]
            chapters = values.get("chapters")
            chapter = values.get("chapter") or (chapters[0] if chapters and len(chapters) == 1 else None)
            try:
                result = await fn(*args, **kwargs)
            except Exception:
                publish_parse_result(flow, novel_id, chapter=chapter, failed=True)
                raise
            publish_parse_result(flow, novel_id, result, chapter=chapter)
            return result

        return wrapper
    return decorate
