"""ComfyUI error payloads carried by existing result/Task metadata JSON fields."""
import json
import re
from urllib.parse import urlsplit, urlunsplit


def safe_url(value):
    if not value:
        return None
    try:
        parsed = urlsplit(str(value))
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parsed.port:
            host += f":{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return "<invalid endpoint>"


def safe_error(value):
    text = str(value or "")
    text = re.sub(r'https?://[^\s<>"\']+', lambda m: safe_url(m.group()), text)
    text = re.sub(r'(?i)(authorization|proxy-authorization|api[_-]?key|token|password)(\s*[:=]\s*)[^\s,;]+', r'\1\2<redacted>', text)
    return text[:2000]


def underlying_exception(exc):
    """Keep the actual OS/transport cause when the outer exception is generic."""
    messages, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        message = str(exc)
        if message and message not in messages:
            messages.append(message)
        exc = exc.__cause__ or exc.__context__
    return safe_error(" · ".join(messages))


def http_error_detail(response):
    detail = response.text.strip()
    try:
        data = response.json()
        if isinstance(data, dict):
            value = data.get("error") or data.get("detail") or data.get("message")
            if isinstance(value, dict):
                value = value.get("underlying_error") or value.get("message") or value.get("detail")
            if isinstance(value, str):
                detail = value
    except (ValueError, TypeError):
        pass
    return safe_error(detail or f"HTTP {response.status_code} (empty response body)")


def error_payload(code, stage, effective_url, underlying_error, *, http_status=None,
                  attempts=0, prompt_submitted=False, configured_url=None):
    result = {
        "error_code": code, "stage": stage, "effective_url": safe_url(effective_url),
        "underlying_error": safe_error(underlying_error), "http_status": http_status,
        "attempts": attempts, "prompt_submitted": bool(prompt_submitted),
    }
    if configured_url:
        result["configured_url"] = safe_url(configured_url)
    return result


def with_error_stage(result, stage, message=None):
    result = dict(result)
    if isinstance(result.get("comfyui_error"), dict):
        result["comfyui_error"] = {**result["comfyui_error"], "stage": stage}
    if message:
        result["message"] = message
    return result


def persist_task_comfyui_error(task, result):
    """Merge only diagnostic metadata; the caller owns status/commit semantics."""
    if not isinstance(result.get("comfyui_error"), dict):
        return
    try:
        metadata = json.loads(task.metadata_json or "{}")
    except (ValueError, TypeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["comfyui_error"] = result["comfyui_error"]
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)


def task_comfyui_error(task):
    try:
        metadata = json.loads(task.metadata_json or "{}")
        error = metadata.get("comfyui_error") if isinstance(metadata, dict) else None
    except (ValueError, TypeError):
        return None
    if not isinstance(error, dict) or not error.get("error_code"):
        return None
    # Project supported diagnostic fields, not arbitrary metadata or credentials.
    result = error_payload(error["error_code"], error.get("stage"), error.get("effective_url"),
                           error.get("underlying_error"), http_status=error.get("http_status"),
                           attempts=error.get("attempts", 0), prompt_submitted=error.get("prompt_submitted", False),
                           configured_url=error.get("configured_url"))
    if error.get("proxy"):
        result["proxy"] = safe_url(error["proxy"])
    return result
