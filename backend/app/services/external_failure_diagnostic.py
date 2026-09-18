"""Pure, bounded v1 diagnostics for failures at external service boundaries."""

from copy import deepcopy
import hashlib
import json
import math
import re
import traceback
from urllib.parse import urlsplit, urlunsplit


VERSION = 1
REDACTION_VERSION = 1
MAX_COMPACT_BYTES = 4 * 1024
MAX_DETAILED_BYTES = 32 * 1024
MAX_RESPONSE_EXCERPT_BYTES = 8 * 1024
MAX_EXCEPTION_MESSAGE_BYTES = 1024
MAX_STACK_BYTES = 16 * 1024
MAX_DEPTH = 8
MAX_MEMBERS = 100

FAILURE_CLASSES = (
    "TIMEOUT",
    "CONNECTION",
    "HTTP_ERROR",
    "INVALID_RESPONSE",
    "INVALID_RECEIPT",
    "REMOTE_REJECTED",
    "REMOTE_EXECUTION_FAILED",
    "LOCAL_IO",
    "CONFIGURATION",
    "VALIDATION",
    "CANCELLED",
    "UNKNOWN",
)

RECEIPT_VIOLATIONS = (
    "IMAGE_RECEIPT_NAME_MISSING_OR_UNSAFE",
    "IMAGE_RECEIPT_TYPE_NOT_INPUT",
    "IMAGE_RECEIPT_SUBFOLDER_MISSING_OR_UNSAFE",
    "SERVICE_UPLOAD_FAILURE_WITHOUT_DIAGNOSTIC",
    "SERVICE_UPLOAD_RESULT_NOT_OBJECT",
    "SERVICE_RECEIPT_TYPE_NOT_INPUT",
    "SERVICE_RECEIPT_FILENAME_MISSING",
    "SERVICE_RECEIPT_PAYLOAD_SHA256_MISMATCH",
    "SERVICE_RECEIPT_PAYLOAD_SIZE_INVALID",
    "SERVICE_RECEIPT_PAYLOAD_SIZE_MISMATCH",
)

_FAILURE_CLASS_SET = frozenset(FAILURE_CLASSES)
_RECEIPT_VIOLATION_SET = frozenset(RECEIPT_VIOLATIONS)
_HASH = re.compile(r"[0-9a-f]{64}")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_SECRET_KEY = re.compile(
    r"^(?:[a-z0-9]+[_-])*(?:api[_-]?key|api[_-]?token|access[_-]?token|refresh[_-]?token|"
    r"auth[_-]?token|token|password|passwd|secret|client[_-]?secret|authorization|"
    r"proxy[_-]?authorization|cookie|cookies|set-cookie)$",
    re.I,
)
_OMITTED_KEY = re.compile(
    r"^(?:headers?|prompt|system_prompt|user_prompt|full_prompt|workflow|workflow_json|graph|"
    r"raw_image|image_bytes|image_data|raw_audio|audio_bytes|audio_data|base64|payload)$",
    re.I,
)
_URL = re.compile(r"https?://[^\s\"'<>]+", re.I)
_DATA_URI = re.compile(r"data:(?:image|audio)/[^;,\s]+(?:;[^,\s]+)*;base64,[A-Za-z0-9+/=]+", re.I)
_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{128,}={0,2}(?![A-Za-z0-9+/=])")
_SAFE_RESPONSE_KEYS = frozenset({
    "code", "detail", "error", "errors", "message", "name", "reason", "status", "subfolder",
    "success", "type",
})
_FREE_TEXT_RESPONSE_KEYS = frozenset({"detail", "error", "message", "reason"})
_SCOPE_FIELDS = (
    "book_id", "chapter_id", "shot_id", "shot_index", "clip_index", "frame_index",
    "reference_index", "task_id", "attempt_kind", "attempt_id", "attempt_no", "retry_no",
)
_TIMING_FIELDS = ("started_at", "finished_at", "elapsed_ms")
_REFERENCE_FIELDS = ("reference_index", "filename", "bytes", "sha256", "source_id", "revision")
_UPSTREAM_FIELDS = ("rsa_id", "rsa_hash", "manifest_hash")
_EXTERNAL_CALL_FIELDS = (
    "endpoint", "method", "timeout_ms", "exception_type", "exception_message", "exception_stack",
    "http_status", "response_content_type", "response_body_sha256", "response_body_bytes",
    "response_excerpt", "response_excerpt_truncated", "receipt_status", "receipt_violation",
)
_SUBMISSION_FIELDS = (
    "queue_called", "submitted", "state", "cid", "queue_seen", "remote_upload_effect",
)
_EVIDENCE_FIELDS = (
    "evidence_id", "path", "sha256", "bytes", "truncated", "redaction_version",
)


def canonical_json_bytes(value):
    """Encode canonical JSON and reject non-finite numbers and non-JSON values."""
    _assert_finite(value)
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("INVALID_DIAGNOSTIC_JSON") from exc


def _assert_finite(value, depth=0, seen=None):
    if depth > 64:
        raise ValueError("DIAGNOSTIC_DEPTH_EXCEEDED")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NON_FINITE_DIAGNOSTIC_NUMBER")
    if isinstance(value, (dict, list, tuple)):
        seen = seen if seen is not None else set()
        identity = id(value)
        if identity in seen:
            raise ValueError("CYCLIC_DIAGNOSTIC_VALUE")
        seen.add(identity)
        values = value.values() if isinstance(value, dict) else value
        for item in values:
            _assert_finite(item, depth + 1, seen)
        seen.remove(identity)


def _truncate_utf8(value, maximum):
    raw = value.encode("utf-8")
    if len(raw) <= maximum:
        return value
    suffix = "...[TRUNCATED]"
    suffix_bytes = suffix.encode("ascii")
    if maximum <= len(suffix_bytes):
        return suffix_bytes[:maximum].decode("ascii", errors="ignore")
    return raw[:maximum - len(suffix_bytes)].decode("utf-8", errors="ignore") + suffix


def sanitize_endpoint(value):
    """Keep only scheme, host, port and path; never retain URL credentials or query data."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("INVALID_DIAGNOSTIC_ENDPOINT")
    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.hostname:
            return None
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        netloc = host + (f":{parsed.port}" if parsed.port is not None else "")
        return _truncate_utf8(urlunsplit((parsed.scheme, netloc, parsed.path or "", "", "")), 2048)
    except (TypeError, ValueError):
        return None


def _sanitize_url_match(match):
    suffix = ""
    candidate = match.group(0)
    while candidate and candidate[-1] in ".,);]}":
        suffix = candidate[-1] + suffix
        candidate = candidate[:-1]
    return (sanitize_endpoint(candidate) or "[REDACTED_URL]") + suffix


def _sanitize_text(value, maximum):
    if not isinstance(value, str):
        value = str(value)
    original = value
    def omit_media(match):
        encoded = match.group(0)
        marker = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"[MEDIA_PAYLOAD_OMITTED sha256={marker} bytes={len(encoded.encode('utf-8'))}]"

    value = _DATA_URI.sub(omit_media, value)
    value = _URL.sub(_sanitize_url_match, value)
    value = re.sub(
        r"(?im)\b(?:proxy-authorization|authorization)\s*[:=]\s*"
        r"(?:(?:Bearer|Basic|Token|Digest|Negotiate|ApiKey)\s+)?[^\r\n]*",
        "Authorization: [REDACTED]",
        value,
    )
    value = re.sub(r"(?i)\b(?:Bearer|Basic)\s+[^\s\"\\]+", lambda match: match.group(0).split()[0] + " [REDACTED]", value)
    value = re.sub(r"(?im)\b(?:set-cookie|cookie)\s*:\s*[^\r\n]*", "cookie=[REDACTED]", value)
    value = re.sub(
        r"(?i)[\"']?\b(api[_-]?key|api[_-]?token|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
        r"token|password|passwd|secret|client[_-]?secret|authorization|cookie)\b[\"']?\s*[:=]\s*"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)",
        lambda match: match.group(1) + "=[REDACTED]",
        value,
    )
    value = re.sub(
        r"(?is)[\"']?\b(prompt|system_prompt|user_prompt|full_prompt|workflow|workflow_json)\b[\"']?\s*[:=].*$",
        lambda match: match.group(1) + "=[OMITTED]",
        value,
    )
    value = re.sub(
        r"(?im)(?<![A-Za-z0-9])[A-Z]:[\\/][^\r\n\"']*",
        "[LOCAL_PATH]",
        value,
    )
    value = re.sub(
        r"(?m)(?<![A-Za-z0-9:/\\])(?:\\\\|//)[^\r\n\"']*",
        "[LOCAL_PATH]",
        value,
    )
    value = re.sub(
        r"(?m)(?<![A-Za-z0-9:/\\])/(?!/)[^\r\n\"']*",
        "[LOCAL_PATH]",
        value,
    )

    def omit_base64(match):
        encoded = match.group(0)
        return f"[BASE64_OMITTED sha256={hashlib.sha256(encoded.encode()).hexdigest()} bytes={len(encoded)}]"

    value = _BASE64.sub(omit_base64, value)
    value = _truncate_utf8(value, maximum)
    return value, value != original, len(original.encode("utf-8")) > maximum


def _safe_arbitrary(value, depth=0, *, allow_scalar=False):
    if depth > MAX_DEPTH:
        return "[DEPTH_LIMIT]"
    if isinstance(value, dict):
        result = {}
        omitted = 0
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_MEMBERS:
                result["__truncated__"] = True
                break
            name = str(key)
            if _SECRET_KEY.fullmatch(name):
                omitted += 1
            elif _is_omitted_key(name):
                omitted += 1
            elif name.lower() not in _SAFE_RESPONSE_KEYS:
                omitted += 1
            elif name.lower() in _FREE_TEXT_RESPONSE_KEYS and isinstance(item, str):
                payload = item.encode("utf-8")
                result[name] = (
                    f"[TEXT_RESPONSE_OMITTED sha256={hashlib.sha256(payload).hexdigest()} bytes={len(payload)}]"
                )
            else:
                result[name] = _safe_arbitrary(item, depth + 1, allow_scalar=True)
        if omitted:
            result["__omitted_fields__"] = omitted
        return result
    if isinstance(value, (list, tuple)):
        if not allow_scalar:
            return ["[OMITTED_RESPONSE_ITEM]"] if value else []
        result = [
            _safe_arbitrary(item, depth + 1, allow_scalar=isinstance(item, dict))
            if isinstance(item, (dict, list, tuple)) else "[OMITTED_RESPONSE_ITEM]"
            for item in value[:MAX_MEMBERS]
        ]
        return result + (["[MEMBER_LIMIT]"] if len(value) > MAX_MEMBERS else [])
    if isinstance(value, bytes):
        return f"[BINARY_OMITTED sha256={hashlib.sha256(value).hexdigest()} bytes={len(value)}]"
    if isinstance(value, str):
        return _sanitize_text(value, MAX_RESPONSE_EXCERPT_BYTES)[0] if allow_scalar else "[OMITTED_RESPONSE_SCALAR]"
    if value is None or isinstance(value, (bool, int, float)):
        return value if allow_scalar else "[OMITTED_RESPONSE_SCALAR]"
    return _sanitize_text(str(value), 512)[0] if allow_scalar else "[OMITTED_RESPONSE_SCALAR]"


def _is_omitted_key(value):
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return bool(_OMITTED_KEY.fullmatch(value) or normalized.endswith(("prompt", "workflow")) or normalized in {
        "prompttext", "systemprompt", "userprompt", "fullprompt", "workflowjson", "graph", "payload",
        "raw", "rawresponse", "image", "images", "audio", "imagebase64", "audiobase64", "imagedata",
        "audiodata", "imagebytes", "audiobytes", "base64", "header", "headers",
    })


def _has_structure_limit(value):
    if isinstance(value, str) and value.startswith((
        "[DEPTH_LIMIT]", "[MEMBER_LIMIT]", "[OMITTED_RESPONSE_", "[TEXT_RESPONSE_OMITTED",
    )):
        return True
    if isinstance(value, dict):
        return (value.get("__truncated__") is True or bool(value.get("__omitted_fields__"))
                or any(_has_structure_limit(item) for item in value.values()))
    if isinstance(value, list):
        return any(_has_structure_limit(item) for item in value)
    return False


def response_body_evidence(body, content_type=None, *, include_excerpt=True):
    """Hash the complete body while retaining only a bounded, redacted textual excerpt."""
    if not isinstance(body, bytes):
        raise ValueError("RESPONSE_BODY_MUST_BE_BYTES")
    _assert_finite(content_type)
    safe_content_type = _sanitize_text(content_type, 256)[0] if content_type is not None else None
    evidence = {
        "response_content_type": safe_content_type,
        "response_body_sha256": hashlib.sha256(body).hexdigest(),
        "response_body_bytes": len(body),
        "response_excerpt": None,
        "response_excerpt_truncated": False,
    }
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    binary = media_type.startswith(("image/", "audio/", "video/")) or media_type == "application/octet-stream"
    if not include_excerpt or binary or b"\x00" in body:
        return evidence
    text = body.decode("utf-8", errors="replace")
    structure_truncated = False
    excerpt_truncated = False
    if media_type not in {"application/json", "application/problem+json"} and not media_type.endswith("+json"):
        evidence["response_excerpt"] = "[UNSTRUCTURED_RESPONSE_OMITTED]"
        evidence["response_excerpt_truncated"] = bool(body)
        return evidence
    try:
        parsed = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NON_FINITE_JSON_NUMBER")))
    except (TypeError, ValueError, RecursionError):
        excerpt = "[MALFORMED_JSON_OMITTED]"
        excerpt_truncated = bool(body)
    else:
        safe = _safe_arbitrary(parsed)
        structure_truncated = _has_structure_limit(safe)
        excerpt = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        excerpt_truncated = len(excerpt.encode("utf-8")) > MAX_RESPONSE_EXCERPT_BYTES
        excerpt = _truncate_utf8(excerpt, MAX_RESPONSE_EXCERPT_BYTES)
    evidence["response_excerpt"] = excerpt
    evidence["response_excerpt_truncated"] = (
        len(text.encode("utf-8")) > MAX_RESPONSE_EXCERPT_BYTES
        or structure_truncated
        or excerpt_truncated
    )
    return evidence


def exception_evidence(error):
    if not isinstance(error, BaseException):
        raise ValueError("INVALID_DIAGNOSTIC_EXCEPTION")
    message, _, message_truncated = _sanitize_text(str(error), MAX_EXCEPTION_MESSAGE_BYTES)
    stack_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    stack, _, stack_truncated = _sanitize_text(stack_text, MAX_STACK_BYTES)
    return {
        "exception_type": type(error).__name__[:128],
        "exception_message": message,
        "exception_stack": stack or None,
        "truncated": message_truncated or stack_truncated,
    }


def _safe_code(value, field):
    if value is None:
        return None
    if not isinstance(value, str) or not _CODE.fullmatch(value):
        raise ValueError(f"INVALID_{field.upper()}")
    return value


def _safe_hash(value, field):
    if value is None:
        return None
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"INVALID_{field.upper()}")
    return value


def _safe_int(value, field, *, minimum=0, maximum=None):
    if value is None:
        return None
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"INVALID_{field.upper()}")
    return value


def _safe_identifier(value, field, maximum=256):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"INVALID_{field.upper()}")
    return value


def _normalize_mapping(value, fields, *, string_limit=512):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("INVALID_DIAGNOSTIC_SECTION")
    _assert_finite(value)
    result, redacted, truncated = {}, False, False
    for field in fields:
        item = value.get(field)
        if isinstance(item, str):
            item, changed, cut = _sanitize_text(item, string_limit)
            redacted = redacted or changed
            truncated = truncated or cut
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise ValueError(f"INVALID_DIAGNOSTIC_{field.upper()}")
        result[field] = item
    return result, redacted, truncated


def _normalize_scope(value):
    result, redacted, truncated = _normalize_mapping(value, _SCOPE_FIELDS)
    for field in ("book_id", "chapter_id", "shot_id", "task_id", "attempt_kind", "attempt_id"):
        result[field] = _safe_identifier(value.get(field), field) if isinstance(value, dict) else None
    for field in ("shot_index", "clip_index", "frame_index", "reference_index", "attempt_no", "retry_no"):
        result[field] = _safe_int(result[field], field)
    return result, redacted, truncated


def _normalize_timing(value):
    result, redacted, truncated = _normalize_mapping(value, _TIMING_FIELDS, string_limit=64)
    elapsed = result["elapsed_ms"]
    if elapsed is not None and (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0):
        raise ValueError("INVALID_ELAPSED_MS")
    return result, redacted, truncated


def _normalize_reference(value):
    result, redacted, truncated = _normalize_mapping(value, _REFERENCE_FIELDS)
    result["source_id"] = _safe_identifier(value.get("source_id"), "source_id") if isinstance(value, dict) else None
    result["reference_index"] = _safe_int(result["reference_index"], "reference_index")
    result["bytes"] = _safe_int(result["bytes"], "reference_bytes")
    result["sha256"] = _safe_hash(result["sha256"], "reference_sha256")
    return result, redacted, truncated


def _normalize_upstream(value):
    result, redacted, truncated = _normalize_mapping(value, _UPSTREAM_FIELDS)
    result["rsa_id"] = _safe_identifier(value.get("rsa_id"), "rsa_id") if isinstance(value, dict) else None
    for field in ("rsa_hash", "manifest_hash"):
        result[field] = _safe_hash(result[field], field)
    return result, redacted, truncated


def _normalize_external_call(value):
    result, redacted, truncated = _normalize_mapping(value, _EXTERNAL_CALL_FIELDS, string_limit=2048)
    result["endpoint"] = sanitize_endpoint(value.get("endpoint")) if isinstance(value, dict) else None
    for field, limit in (("exception_message", MAX_EXCEPTION_MESSAGE_BYTES), ("exception_stack", MAX_STACK_BYTES),
                         ("response_excerpt", MAX_RESPONSE_EXCERPT_BYTES)):
        source = value.get(field) if isinstance(value, dict) else None
        if source is not None:
            if not isinstance(source, str):
                raise ValueError(f"INVALID_{field.upper()}")
            result[field], changed, cut = _sanitize_text(source, limit)
            redacted = redacted or changed
            truncated = truncated or cut
    result["timeout_ms"] = _safe_int(result["timeout_ms"], "timeout_ms")
    result["http_status"] = _safe_int(result["http_status"], "http_status", minimum=100, maximum=599)
    result["response_body_bytes"] = _safe_int(result["response_body_bytes"], "response_body_bytes")
    result["response_body_sha256"] = _safe_hash(result["response_body_sha256"], "response_body_sha256")
    if result["response_excerpt_truncated"] not in (None, True, False):
        raise ValueError("INVALID_RESPONSE_EXCERPT_TRUNCATED")
    violation = result["receipt_violation"]
    if violation is not None and violation not in _RECEIPT_VIOLATION_SET:
        raise ValueError("INVALID_RECEIPT_VIOLATION")
    redacted = redacted or any(
        marker in item
        for item in result.values() if isinstance(item, str)
        for marker in ("[REDACTED]", "[OMITTED]", "[MEDIA_PAYLOAD_OMITTED", "[BASE64_OMITTED",
                       "[OMITTED_RESPONSE_", "[TEXT_RESPONSE_OMITTED", "[LOCAL_PATH]")
    )
    redacted = redacted or result["response_excerpt_truncated"] is True
    return result, redacted, truncated or result["response_excerpt_truncated"] is True


def _normalize_submission(value):
    result, redacted, truncated = _normalize_mapping(value, _SUBMISSION_FIELDS, string_limit=128)
    for field in ("queue_called", "submitted", "queue_seen"):
        if result[field] not in (None, True, False):
            raise ValueError(f"INVALID_{field.upper()}")
    if result["state"] == "NOT_SUBMITTED" and (
        result["queue_called"] is not False or result["submitted"] is not False
        or result["cid"] is not None or result["queue_seen"] is not False
    ):
        raise ValueError("INVALID_NOT_SUBMITTED_FACTS")
    if result["submitted"] is False and result["cid"] is not None:
        raise ValueError("CID_REQUIRES_SUBMISSION")
    if result["cid"] is not None and result["submitted"] is not True:
        raise ValueError("CID_REQUIRES_SUBMISSION")
    if result["queue_called"] is False and result["submitted"] is True:
        raise ValueError("SUBMISSION_REQUIRES_QUEUE")
    return result, redacted, truncated


def _normalize_evidence(value):
    result, redacted, truncated = _normalize_mapping(value, _EVIDENCE_FIELDS, string_limit=512)
    result["sha256"] = _safe_hash(result["sha256"], "evidence_sha256")
    result["bytes"] = _safe_int(result["bytes"], "evidence_bytes")
    raw_path = value.get("path") if isinstance(value, dict) else None
    if raw_path:
        if not isinstance(raw_path, str):
            raise ValueError("INVALID_EVIDENCE_PATH")
        result["path"] = _sanitize_text(raw_path.replace("\\", "/").split("/")[-1], 512)[0]
    raw_id = value.get("evidence_id") if isinstance(value, dict) else None
    if raw_id is not None:
        if not isinstance(raw_id, str) or not re.fullmatch(r"ev1_[0-9a-f]{64}", raw_id):
            raise ValueError("INVALID_EVIDENCE_ID")
        result["evidence_id"] = raw_id
    elif result["sha256"]:
        result["evidence_id"] = "ev1_" + result["sha256"]
    if result["truncated"] not in (None, True, False):
        raise ValueError("INVALID_EVIDENCE_TRUNCATED")
    if result["redaction_version"] is not None and result["redaction_version"] != REDACTION_VERSION:
        raise ValueError("INVALID_REDACTION_VERSION")
    return result, redacted, truncated


def _json_size(value):
    return len(canonical_json_bytes(value))


def _string_paths(value, prefix=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _string_paths(item, prefix + (key,))
    elif isinstance(value, str):
        yield prefix, value


def _set_path(value, path, replacement):
    owner = value
    for key in path[:-1]:
        owner = owner[key]
    owner[path[-1]] = replacement


def _bound(value, maximum):
    value = deepcopy(value)
    if _json_size(value) <= maximum:
        return value
    value["truncated"] = True
    protected = {
        "diagnostic_id", "error_code", "failure_class", "level", "stage", "operation", "service",
        "book_id", "chapter_id", "shot_id", "task_id", "attempt_kind", "attempt_id", "source_id",
        "rsa_id", "rsa_hash", "manifest_hash", "sha256", "response_body_sha256", "evidence_id",
        "receipt_violation",
    }
    while _json_size(value) > maximum:
        candidates = [(path, text) for path, text in _string_paths(value) if path[-1] not in protected and text]
        if not candidates:
            break
        path, text = max(candidates, key=lambda item: len(item[1].encode("utf-8")))
        current = len(text.encode("utf-8"))
        replacement = (None if current <= 16 or (path[-1] in {"exception_stack", "response_excerpt"} and current <= 256)
                       else _truncate_utf8(text, max(16, current // 2)))
        _set_path(value, path, replacement)
    if _json_size(value) > maximum:
        raise ValueError("DIAGNOSTIC_SIZE_LIMIT_UNSATISFIABLE")
    return value


class ExternalFailureDiagnostic:
    """Factory only: diagnostics describe evidence and never return a business decision."""

    failure_classes = FAILURE_CLASSES

    @classmethod
    def build(
        cls, *, operation_key, error_code, failure_class, level="ERROR", stage, operation,
        service, provider=None, scope=None, timing=None, reference=None, upstream=None,
        external_call=None, submission=None, evidence=None, maximum=MAX_DETAILED_BYTES,
    ):
        if failure_class not in _FAILURE_CLASS_SET:
            raise ValueError("INVALID_FAILURE_CLASS")
        if not isinstance(operation_key, dict) or not operation_key:
            raise ValueError("INVALID_OPERATION_KEY")
        operation_bytes = canonical_json_bytes(operation_key)
        if maximum <= 0 or maximum > MAX_DETAILED_BYTES:
            raise ValueError("INVALID_DIAGNOSTIC_SIZE_LIMIT")
        normalized = []
        for normalizer, value in (
            (_normalize_scope, scope), (_normalize_timing, timing), (_normalize_reference, reference),
            (_normalize_upstream, upstream), (_normalize_external_call, external_call),
            (_normalize_submission, submission), (_normalize_evidence, evidence),
        ):
            normalized.append(normalizer(value))
        sections = [item[0] for item in normalized]
        redacted = any(item[1] for item in normalized)
        truncated = any(item[2] for item in normalized)
        diagnostic = {
            "version": VERSION,
            "diagnostic_id": "efd1_" + hashlib.sha256(operation_bytes).hexdigest(),
            "error_code": _safe_code(error_code, "error_code"),
            "failure_class": failure_class,
            "level": _safe_code(level, "level"),
            "stage": _safe_code(stage, "stage"),
            "operation": _safe_code(operation, "operation"),
            "service": _sanitize_text(service, 128)[0] if isinstance(service, str) and service else None,
            "provider": _sanitize_text(provider, 128)[0] if isinstance(provider, str) and provider else None,
            "scope": sections[0],
            "timing": sections[1],
            "reference": sections[2],
            "upstream": sections[3],
            "external_call": sections[4],
            "submission": sections[5],
            "evidence": sections[6],
            "redacted": redacted,
            "truncated": truncated,
        }
        if diagnostic["service"] is None:
            raise ValueError("INVALID_DIAGNOSTIC_SERVICE")
        return _bound(diagnostic, maximum)

    @classmethod
    def rebind(
        cls, source, *, operation_key, scope, reference=None, upstream=None, external_call=None,
        submission=None, evidence=None, error_code=None, maximum=MAX_DETAILED_BYTES,
    ):
        _assert_finite(source)
        if not isinstance(source, dict) or source.get("version") != VERSION:
            raise ValueError("INVALID_EXTERNAL_FAILURE_DIAGNOSTIC")
        merged_reference = {**(source.get("reference") or {}), **(reference or {})}
        merged_upstream = {**(source.get("upstream") or {}), **(upstream or {})}
        merged_call = {**(source.get("external_call") or {}), **(external_call or {})}
        rebound = cls.build(
            operation_key=operation_key,
            error_code=error_code or source.get("error_code"),
            failure_class=source.get("failure_class"),
            level=source.get("level"),
            stage=source.get("stage"),
            operation=source.get("operation"),
            service=source.get("service"),
            provider=source.get("provider"),
            scope=scope,
            timing=source.get("timing"),
            reference=merged_reference,
            upstream=merged_upstream,
            external_call=merged_call,
            submission=submission if submission is not None else source.get("submission"),
            evidence=evidence,
            maximum=maximum,
        )
        rebound["redacted"] = rebound["redacted"] or source.get("redacted") is True
        rebound["truncated"] = rebound["truncated"] or source.get("truncated") is True
        return _bound(rebound, maximum)

    @classmethod
    def compact(cls, source, *, evidence=None):
        _assert_finite(source)
        if not isinstance(source, dict) or source.get("version") != VERSION:
            raise ValueError("INVALID_EXTERNAL_FAILURE_DIAGNOSTIC")
        compact = {key: deepcopy(source.get(key)) for key in (
            "version", "diagnostic_id", "error_code", "failure_class", "level", "stage", "operation",
            "service", "provider", "scope", "timing", "reference", "upstream", "submission",
        )}
        call = source.get("external_call") or {}
        compact["external_call"] = {key: deepcopy(call.get(key)) for key in _EXTERNAL_CALL_FIELDS
                                    if key not in {"exception_stack", "response_excerpt"}}
        compact["evidence"] = _normalize_evidence(evidence if evidence is not None else source.get("evidence"))[0]
        compact["redacted"] = source.get("redacted") is True
        compact["truncated"] = source.get("truncated") is True or compact["evidence"].get("truncated") is True
        return _bound(compact, MAX_COMPACT_BYTES)


__all__ = [
    "ExternalFailureDiagnostic", "FAILURE_CLASSES", "RECEIPT_VIOLATIONS", "VERSION",
    "REDACTION_VERSION", "MAX_COMPACT_BYTES", "MAX_DETAILED_BYTES", "MAX_RESPONSE_EXCERPT_BYTES",
    "MAX_EXCEPTION_MESSAGE_BYTES", "MAX_STACK_BYTES", "canonical_json_bytes", "exception_evidence",
    "response_body_evidence", "sanitize_endpoint",
]
