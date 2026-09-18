"""Pure Stage A diagnostic contract tests; no application startup or I/O."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.PURE

MODULE_PATH = Path(__file__).resolve().parents[1] / "app/services/external_failure_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("_external_failure_diagnostic_contract", MODULE_PATH)
diagnostics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostics)


def build(**changes):
    values = {
        "operation_key": {
            "task_id": "task-1", "attempt_id": "clip-attempt-1", "operation": "UPLOAD_IMAGE",
            "reference_index": 2, "invocation_no": 1,
        },
        "error_code": "VALIDATED_REFERENCE_UPLOAD_FAILED",
        "failure_class": "TIMEOUT",
        "stage": "REFERENCE_UPLOAD",
        "operation": "UPLOAD_IMAGE",
        "service": "comfyui",
        "provider": "comfyui",
        "scope": {
            "book_id": "book", "chapter_id": "chapter", "shot_id": "shot", "shot_index": 2,
            "clip_index": 1, "frame_index": None, "reference_index": 2, "task_id": "task-1",
            "attempt_kind": "VIDEO_CLIP", "attempt_id": "clip-attempt-1", "attempt_no": 1,
            "retry_no": 0,
        },
        "reference": {
            "reference_index": 2, "filename": "visual-state-test.png", "bytes": 123,
            "sha256": hashlib.sha256(b"image").hexdigest(),
        },
        "external_call": {
            "endpoint": "http://comfy.test/upload/image", "method": "POST", "timeout_ms": 30000,
            "exception_type": "ReadTimeout", "exception_message": "timed out",
            "receipt_status": "NOT_RECEIVED",
        },
        "submission": {
            "queue_called": False, "submitted": False, "state": "NOT_SUBMITTED", "cid": None,
            "queue_seen": False, "remote_upload_effect": "UNKNOWN",
        },
    }
    values.update(changes)
    return diagnostics.ExternalFailureDiagnostic.build(**values)


def test_v1_closed_enum_canonical_id_and_nonfinite_rejection():
    assert diagnostics.FAILURE_CLASSES == (
        "TIMEOUT", "CONNECTION", "HTTP_ERROR", "INVALID_RESPONSE", "INVALID_RECEIPT",
        "REMOTE_REJECTED", "REMOTE_EXECUTION_FAILED", "LOCAL_IO", "CONFIGURATION",
        "VALIDATION", "CANCELLED", "UNKNOWN",
    )
    first = build()
    reordered = build(operation_key={
        "invocation_no": 1, "reference_index": 2, "operation": "UPLOAD_IMAGE",
        "attempt_id": "clip-attempt-1", "task_id": "task-1",
    })
    assert first["diagnostic_id"] == reordered["diagnostic_id"]
    assert diagnostics.canonical_json_bytes(first) == diagnostics.canonical_json_bytes(reordered)
    assert not {"retryable", "retry", "decision", "action"}.intersection(first)

    with pytest.raises(ValueError, match="INVALID_FAILURE_CLASS"):
        build(failure_class="TIMEOUT_OR_CONNECTION")
    with pytest.raises(ValueError, match="NON_FINITE"):
        build(operation_key={"elapsed": float("nan")})
    with pytest.raises(ValueError, match="NON_FINITE"):
        build(scope={"clip_index": float("inf")})
    with pytest.raises(ValueError, match="INVALID_NOT_SUBMITTED_FACTS"):
        build(submission={
            "queue_called": False, "submitted": False, "state": "NOT_SUBMITTED", "cid": "not-a-cid",
            "queue_seen": False,
        })


def test_response_and_exception_evidence_are_redacted_without_losing_body_identity():
    secret_body = json.dumps({
        "authorization": "Bearer body-secret",
        "nested": {"api_token": "token-secret", "password": "password-secret", "cookie": "session-secret"},
        "prompt": "full prompt must not persist",
        "workflow": {"huge": "full workflow must not persist"},
        "image_data": "A" * 512,
        "detail": "provider unavailable",
    }).encode()
    response = diagnostics.response_body_evidence(secret_body, "application/json; charset=utf-8")
    try:
        raise RuntimeError(
            "Bearer exception-secret password=hidden "
            "https://alice:pw@comfy.test/upload/image?token=query-secret#fragment "
            "/Volumes/Data/private.png Cookie: sid=cookie-secret "
            "data:audio/wav;base64," + "B" * 2048
        )
    except RuntimeError as error:
        exception = diagnostics.exception_evidence(error)

    detail = build(
        external_call={
            "endpoint": "http://alice:pw@comfy.test:8288/upload/image?token=query-secret#fragment",
            "method": "POST", "timeout_ms": 30000, "receipt_status": "NOT_RECEIVED",
            **response, **{key: value for key, value in exception.items() if key != "truncated"},
        },
    )
    encoded = diagnostics.canonical_json_bytes(detail)
    text = encoded.decode()
    assert detail["external_call"]["endpoint"] == "http://comfy.test:8288/upload/image"
    assert detail["external_call"]["response_body_sha256"] == hashlib.sha256(secret_body).hexdigest()
    assert detail["external_call"]["response_body_bytes"] == len(secret_body)
    assert detail["external_call"]["response_content_type"] == "application/json; charset=utf-8"
    assert "provider unavailable" not in detail["external_call"]["response_excerpt"]
    assert "[TEXT_RESPONSE_OMITTED" in detail["external_call"]["response_excerpt"]
    for forbidden in (
        "body-secret", "token-secret", "password-secret", "full prompt must not persist",
        "full workflow must not persist", "exception-secret", "query-secret", "alice:pw",
        "/Volumes/Data/private.png", "session-secret", "cookie-secret", "B" * 128,
    ):
        assert forbidden not in text
    assert "[REDACTED]" in text and "__omitted_fields__" in text and "[LOCAL_PATH]" in text
    assert len(detail["external_call"]["exception_message"].encode()) <= diagnostics.MAX_EXCEPTION_MESSAGE_BYTES
    assert len(detail["external_call"]["exception_stack"].encode()) <= diagnostics.MAX_STACK_BYTES
    assert len(encoded) <= diagnostics.MAX_DETAILED_BYTES


def test_malformed_json_and_unknown_fields_cannot_persist_secret_or_prompt_values():
    malformed = b'{"password":"malformed-secret","prompt":"full malformed prompt'
    malformed_evidence = diagnostics.response_body_evidence(malformed, "application/json")
    assert "malformed-secret" not in malformed_evidence["response_excerpt"]
    assert "full malformed prompt" not in malformed_evidence["response_excerpt"]
    parsed = json.dumps({
        "message": "safe summary",
        "unexpected_payload": "unlabelled full prompt or secret",
        "detail": {"unknown_nested": "secret nested value", "code": "REMOTE_DOWN"},
    }).encode()
    parsed_evidence = diagnostics.response_body_evidence(parsed, "application/json")
    assert "safe summary" not in parsed_evidence["response_excerpt"]
    assert "[TEXT_RESPONSE_OMITTED" in parsed_evidence["response_excerpt"]
    assert "unlabelled full prompt or secret" not in parsed_evidence["response_excerpt"]
    assert "secret nested value" not in parsed_evidence["response_excerpt"]
    assert "REMOTE_DOWN" in parsed_evidence["response_excerpt"]
    assert parsed_evidence["response_excerpt_truncated"] is True
    list_evidence = diagnostics.response_body_evidence(
        json.dumps(["sk-live-secret", "full prompt prose"]).encode(), "application/json",
    )
    assert "sk-live-secret" not in list_evidence["response_excerpt"]
    assert "full prompt prose" not in list_evidence["response_excerpt"]
    key_secret = diagnostics.response_body_evidence(
        json.dumps({"sk-live-secret-key-name": "safe-looking-value"}).encode(), "application/json",
    )
    assert "sk-live-secret-key-name" not in key_secret["response_excerpt"]
    redacted_detail = build(external_call={
        "endpoint": "http://comfy.test/upload/image", "method": "POST", "timeout_ms": 30000,
        "receipt_status": "INVALID_RESPONSE", **key_secret,
    })
    assert redacted_detail["redacted"] is True and redacted_detail["truncated"] is True


def test_detailed_and_compact_bounds_preserve_hashes_and_evidence_pointer():
    body = ("token=super-secret " + "response " * 5000).encode()
    response = diagnostics.response_body_evidence(body, "text/plain")
    detail = build(
        scope={
            "book_id": "b" * 100, "chapter_id": "c" * 100, "shot_id": "s" * 100,
            "shot_index": 2, "clip_index": 1, "reference_index": 2, "task_id": "t" * 100,
            "attempt_kind": "VIDEO_CLIP", "attempt_id": "a" * 100, "attempt_no": 1,
        },
        reference={
            "reference_index": 2, "filename": "f" * 5000 + ".png", "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        },
        external_call={
            "endpoint": "http://comfy.test/upload/image", "method": "POST", "timeout_ms": 30000,
            "exception_type": "ReadTimeout", "exception_message": "message " * 1000,
            "exception_stack": "stack\n" * 10000, "receipt_status": "NOT_RECEIVED", **response,
        },
    )
    detailed_bytes = diagnostics.canonical_json_bytes(detail)
    assert len(detailed_bytes) <= diagnostics.MAX_DETAILED_BYTES
    assert detail["external_call"]["response_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert detail["external_call"]["response_body_bytes"] == len(body)
    assert detail["external_call"]["response_content_type"] == "text/plain"
    assert len(detail["external_call"]["response_excerpt"].encode()) <= diagnostics.MAX_RESPONSE_EXCERPT_BYTES

    evidence_sha = hashlib.sha256(detailed_bytes).hexdigest()
    compact = diagnostics.ExternalFailureDiagnostic.compact(detail, evidence={
        "path": "/private/task/worker-result-secret.json", "sha256": evidence_sha,
        "bytes": len(detailed_bytes), "truncated": detail["truncated"], "redaction_version": 1,
    })
    assert len(diagnostics.canonical_json_bytes(compact)) <= diagnostics.MAX_COMPACT_BYTES
    assert compact["evidence"] == {
        "evidence_id": "ev1_" + evidence_sha,
        "path": "worker-result-secret.json",
        "sha256": evidence_sha,
        "bytes": len(detailed_bytes),
        "truncated": detail["truncated"],
        "redaction_version": 1,
    }
    assert compact["diagnostic_id"] == detail["diagnostic_id"]
    assert compact["external_call"]["response_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert "response_excerpt" not in compact["external_call"]
    assert "exception_stack" not in compact["external_call"]


def test_compact_bound_never_truncates_trusted_provenance_identifiers():
    identifiers = {
        "book_id": "book-" + "b" * 200,
        "chapter_id": "chapter-" + "c" * 200,
        "shot_id": "shot-" + "s" * 200,
        "task_id": "task-" + "t" * 200,
        "attempt_kind": "VIDEO_CLIP",
        "attempt_id": "attempt-" + "a" * 200,
    }
    detail = build(
        scope={**identifiers, "shot_index": 2, "clip_index": 1, "reference_index": 0},
        reference={"reference_index": 0, "source_id": "artifact-" + "i" * 200,
                   "filename": "x" * 500 + ".png", "bytes": 10, "sha256": "1" * 64},
        upstream={"rsa_id": "rsa-" + "r" * 200, "rsa_hash": "2" * 64, "manifest_hash": "3" * 64},
        external_call={"endpoint": "http://comfy.test/upload/image", "method": "POST", "timeout_ms": 30000,
                       "exception_type": "ReadTimeout", "exception_message": "large " * 1000,
                       "receipt_status": "NOT_RECEIVED"},
    )
    compact = diagnostics.ExternalFailureDiagnostic.compact(detail)
    assert len(diagnostics.canonical_json_bytes(compact)) <= diagnostics.MAX_COMPACT_BYTES
    assert {key: compact["scope"][key] for key in identifiers} == identifiers
    assert compact["reference"]["source_id"] == "artifact-" + "i" * 200
    assert compact["upstream"] == {
        "rsa_id": "rsa-" + "r" * 200, "rsa_hash": "2" * 64, "manifest_hash": "3" * 64,
    }


def test_binary_response_keeps_identity_without_excerpt():
    body = b"\x89PNG\r\n\x1a\n\x00secret raw image"
    evidence = diagnostics.response_body_evidence(body, "image/png")
    assert evidence == {
        "response_content_type": "image/png",
        "response_body_sha256": hashlib.sha256(body).hexdigest(),
        "response_body_bytes": len(body),
        "response_excerpt": None,
        "response_excerpt_truncated": False,
    }


def test_exception_redaction_removes_authorization_token_posix_windows_and_unc_paths():
    canaries = (
        "STAGE_A_AUTH_CANARY_9465",
        "/srv/novelflow/private project/reference.png",
        r"C:\ComfyUI\private project\reference.png",
        r"\\fileserver\private share\reference.png",
    )
    try:
        raise RuntimeError(
            "Authorization: Token STAGE_A_AUTH_CANARY_9465\n"
            "posix: /srv/novelflow/private project/reference.png\n"
            "windows: " + r"C:\ComfyUI\private project\reference.png" + "\n"
            "unc: " + r"\\fileserver\private share\reference.png"
        )
    except RuntimeError as error:
        evidence = diagnostics.exception_evidence(error)
    encoded = json.dumps(evidence, ensure_ascii=False)
    assert all(canary not in encoded for canary in canaries)
    assert "Authorization=[REDACTED]" in encoded
    assert encoded.count("[LOCAL_PATH]") >= 3
    assert evidence["truncated"] is False


def test_rebind_adds_trusted_reference_and_upstream_scope():
    detail = build(scope={"reference_index": 2})
    rebound = diagnostics.ExternalFailureDiagnostic.rebind(
        detail,
        operation_key={"task_id": "task-1", "attempt_id": "attempt-1", "operation": "UPLOAD_IMAGE",
                       "reference_index": 2, "invocation_no": 1},
        scope={"book_id": "book", "chapter_id": "chapter", "shot_id": "shot", "shot_index": 2,
               "clip_index": 1, "reference_index": 2, "task_id": "task-1", "attempt_kind": "VIDEO_CLIP",
               "attempt_id": "attempt-1", "attempt_no": 1},
        reference={"reference_index": 2, "source_id": "artifact-3"},
        upstream={"rsa_id": "rsa-1", "rsa_hash": "a" * 64, "manifest_hash": "b" * 64},
        submission={"queue_called": False, "submitted": False, "state": "NOT_SUBMITTED", "cid": None,
                    "queue_seen": False, "remote_upload_effect": "UNKNOWN"},
    )
    assert rebound["reference"]["source_id"] == "artifact-3"
    assert rebound["upstream"] == {"rsa_id": "rsa-1", "rsa_hash": "a" * 64, "manifest_hash": "b" * 64}
