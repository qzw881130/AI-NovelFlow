"""Standalone client tests: Python 3.11, --noconftest, no app startup or network."""

import ast
import asyncio
from contextlib import asynccontextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, mock_open

import httpx
import pytest


pytestmark = pytest.mark.PURE

CLIENT_PATH = Path(__file__).resolve().parents[1] / "app/services/comfyui/client.py"
DIAGNOSTIC_PATH = Path(__file__).resolve().parents[1] / "app/services/external_failure_diagnostic.py"
UPLOAD_NAME = "keyframe_0123456789abcdef.png"
PAYLOAD = b"\x89PNG\r\n\x1a\nresolved snapshot\x00\xff"
UPLOADED = "\u4e0a\u4f20\u6210\u529f"
RECEIPT = {"name": "server-renamed.png", "subfolder": "", "type": "input"}
UNSAFE_NAMES = [
    "", ".", "..", ".hidden.png", "../escape.png", "dir/image.png",
    "/absolute.png", "dir\\image.png", "..\\escape.png", "C:image.png",
    "C:\\image.png", "image\x00.png", "image\n.png", "image\r.png",
    "image\t.png", "image\x7f.png", "\u53c2\u8003.png", "image name.png",
    "%2e%2e.png", "image[output].png", "image.png.", "image..png",
    7, False, [], {},
]


@pytest.fixture
def boundary(monkeypatch):
    # Load only the real client module, bypassing app/services package imports.
    app = sys.modules.get("app")
    if app is None:
        app = ModuleType("app")
        app.__path__ = [str(CLIENT_PATH.parents[3] / "app")]
        monkeypatch.setitem(sys.modules, "app", app)
    services = sys.modules.get("app.services")
    if services is None:
        services = ModuleType("app.services")
        services.__path__ = [str(CLIENT_PATH.parents[1])]
        monkeypatch.setitem(sys.modules, "app.services", services)
        monkeypatch.setattr(app, "services", services, raising=False)
    diagnostic_spec = importlib.util.spec_from_file_location(
        "app.services.external_failure_diagnostic", DIAGNOSTIC_PATH,
    )
    diagnostic_module = importlib.util.module_from_spec(diagnostic_spec)
    monkeypatch.setitem(sys.modules, diagnostic_spec.name, diagnostic_module)
    diagnostic_spec.loader.exec_module(diagnostic_module)
    monkeypatch.setattr(services, "external_failure_diagnostic", diagnostic_module, raising=False)

    spec = importlib.util.spec_from_file_location("_keyframe_upload_client", CLIENT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.ComfyUIClient, "base_url", property(lambda self: "http://comfyui.test"))
    state = SimpleNamespace(
        client=module.ComfyUIClient(),
        response=httpx.Response(200, json=RECEIPT),
        error=None,
        calls=[],
        diagnostics=diagnostic_module,
    )

    async def post(url, *, files, data, timeout):
        content = files["image"][1]
        state.calls.append({
            "url": url, "files": files, "data": data, "timeout": timeout,
            "body": content if isinstance(content, bytes) else content.read(),
        })
        if state.error is not None:
            raise state.error
        return state.response

    state.post = AsyncMock(side_effect=post)

    @asynccontextmanager
    async def http_client():
        yield SimpleNamespace(post=state.post)

    state.factory = Mock(side_effect=http_client)
    monkeypatch.setattr(state.client, "_client", state.factory)
    return state


def assert_failure(result, failure_class=None):
    assert set(result) == {"success", "message", "external_failure"}
    assert result["success"] is False
    assert isinstance(result["message"], str) and result["message"]
    diagnostic = result["external_failure"]
    assert diagnostic["version"] == 1
    assert diagnostic["error_code"] == "VALIDATED_REFERENCE_UPLOAD_FAILED"
    if failure_class:
        assert diagnostic["failure_class"] == failure_class
    assert len(json.dumps(diagnostic, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()) <= 32 * 1024


@pytest.mark.parametrize("source_state", ["deleted", "changed"])
@pytest.mark.parametrize("subfolder", ["", "references/run-7.v2"])
def test_snapshot_upload_uses_identical_frozen_bytes_and_server_locator(
    boundary, monkeypatch, tmp_path, source_state, subfolder,
):
    path = tmp_path / "reference.jpg"
    path.write_bytes(PAYLOAD)
    snapshot = path.read_bytes()
    expected_hash = hashlib.sha256(snapshot).hexdigest()
    if source_state == "deleted":
        path.unlink()
    else:
        path.write_bytes(b"different local contents")

    boundary.response = httpx.Response(200, json={
        **RECEIPT, "subfolder": subfolder, "payload_sha256": "untrusted server hash",
        "payload_size": 1, "extra": "not part of the receipt contract",
    })
    no_filesystem = Mock(side_effect=AssertionError("snapshot must not access the local path"))
    monkeypatch.setattr("builtins.open", no_filesystem)
    monkeypatch.setattr(os.path, "exists", no_filesystem)
    monkeypatch.setattr(os.path, "isfile", no_filesystem)
    monkeypatch.setattr(Path, "read_bytes", no_filesystem)
    hash_spy = Mock(wraps=hashlib.sha256)
    monkeypatch.setattr(hashlib, "sha256", hash_spy)

    result = asyncio.run(boundary.client.upload_image(
        str(path), upload_name=UPLOAD_NAME, payload=snapshot,
    ))

    name = RECEIPT["name"]
    assert result == {
        "success": True,
        "filename": f"{subfolder}/{name}" if subfolder else name,
        "subfolder": subfolder,
        "type": "input",
        "payload_sha256": expected_hash,
        "payload_size": len(snapshot),
        "message": UPLOADED,
    }
    no_filesystem.assert_not_called()
    boundary.factory.assert_called_once_with()
    boundary.post.assert_awaited_once()
    assert boundary.calls == [{
        "url": "http://comfyui.test/upload/image",
        "files": {"image": (UPLOAD_NAME, snapshot, "image/png")},
        "data": {"type": "input", "overwrite": "true"},
        "timeout": 30.0,
        "body": snapshot,
    }]
    assert boundary.calls[0]["files"]["image"][1] is snapshot
    hash_spy.assert_called_once_with(snapshot)
    assert hash_spy.call_args.args[0] is snapshot


def test_opt_in_without_payload_reads_file_once_into_bytes(boundary, monkeypatch, tmp_path):
    path = tmp_path / "reference.webp"
    path.write_bytes(PAYLOAD)
    file_open = mock_open()
    file_open.return_value.read.return_value = PAYLOAD
    monkeypatch.setattr("builtins.open", file_open)
    local_check = Mock(wraps=os.path.isfile)
    monkeypatch.setattr(os.path, "isfile", local_check)

    result = asyncio.run(boundary.client.upload_image(str(path), upload_name=UPLOAD_NAME))

    local_check.assert_called_once_with(str(path))
    file_open.assert_called_once_with(str(path), "rb")
    file_open.return_value.read.assert_called_once_with()
    file_open.return_value.__exit__.assert_called_once()
    boundary.post.assert_awaited_once()
    part = boundary.calls[0]["files"]["image"]
    assert part == (UPLOAD_NAME, PAYLOAD, "image/png")
    assert part[1] is file_open.return_value.read.return_value
    assert result == {
        "success": True, "filename": RECEIPT["name"], "subfolder": "", "type": "input",
        "payload_sha256": hashlib.sha256(part[1]).hexdigest(),
        "payload_size": len(part[1]), "message": UPLOADED,
    }


@pytest.mark.parametrize("options", [{}, {"upload_name": None, "payload": None}])
@pytest.mark.parametrize("receipt, expected_name", [
    ({"name": "remote.png", "subfolder": "ignored", "type": "output"}, "remote.png"),
    ({}, "\u53c2\u8003\u56fe.jpg"),
    ({"name": ""}, ""),
    ({"name": None}, None),
])
def test_legacy_chinese_filename_stream_and_return_shape_unchanged(
    boundary, tmp_path, options, receipt, expected_name,
):
    path = tmp_path / "\u53c2\u8003\u56fe.jpg"
    path.write_bytes(PAYLOAD)
    boundary.response = httpx.Response(200, json=receipt)

    result = asyncio.run(boundary.client.upload_image(str(path), **options))

    assert result == {"success": True, "filename": expected_name, "message": UPLOADED}
    boundary.factory.assert_called_once_with()
    boundary.post.assert_awaited_once()
    call = boundary.calls[0]
    filename, stream, mime = call["files"]["image"]
    assert filename == path.name
    assert stream.closed
    assert mime == "image/png"
    assert call["body"] == PAYLOAD
    assert call["data"] == {"type": "input", "overwrite": "true"}
    assert call["timeout"] == 30.0
    assert call["url"] == "http://comfyui.test/upload/image"


def test_legacy_missing_path_error_unchanged(boundary, tmp_path):
    path = tmp_path / "missing.png"
    result = asyncio.run(boundary.client.upload_image(str(path)))
    assert result == {
        "success": False, "message": f"\u56fe\u7247\u6587\u4ef6\u4e0d\u5b58\u5728: {path}",
    }
    boundary.factory.assert_not_called()


def test_legacy_failed_http_error_unchanged(boundary, tmp_path):
    path = tmp_path / "reference.png"
    path.write_bytes(PAYLOAD)
    boundary.response = httpx.Response(500, text="server error")
    result = asyncio.run(boundary.client.upload_image(str(path)))
    assert result == {"success": False, "message": "\u4e0a\u4f20\u5931\u8d25: server error"}
    boundary.post.assert_awaited_once()


@pytest.mark.parametrize("payload", [PAYLOAD, b"", "not bytes", bytearray(b"x")])
def test_payload_requires_opt_in_name(boundary, payload):
    result = asyncio.run(boundary.client.upload_image("missing.png", payload=payload))
    assert {key: result[key] for key in ("success", "message")} == {
        "success": False, "message": "payload requires upload_name",
    }
    assert_failure(result, "VALIDATION")
    boundary.factory.assert_not_called()


def test_new_arguments_are_keyword_only(boundary):
    with pytest.raises(TypeError):
        boundary.client.upload_image("missing.png", UPLOAD_NAME, PAYLOAD)
    boundary.factory.assert_not_called()


@pytest.mark.parametrize("upload_name", UNSAFE_NAMES)
def test_invalid_upload_name_stops_before_filesystem_or_http(boundary, monkeypatch, upload_name):
    no_filesystem = Mock(side_effect=AssertionError("invalid name must not read a file"))
    monkeypatch.setattr("builtins.open", no_filesystem)
    monkeypatch.setattr(os.path, "isfile", no_filesystem)
    result = asyncio.run(boundary.client.upload_image("missing.png", upload_name=upload_name))
    assert result["message"] == "Invalid upload_name: expected a safe ASCII basename"
    assert_failure(result, "VALIDATION")
    no_filesystem.assert_not_called()
    boundary.factory.assert_not_called()


@pytest.mark.parametrize("payload", [b"", bytearray(b"x"), memoryview(b"x"), "x", 1, False])
def test_invalid_payload_stops_without_filesystem_or_http(boundary, monkeypatch, payload):
    no_filesystem = Mock(side_effect=AssertionError("supplied payload must not read a file"))
    monkeypatch.setattr("builtins.open", no_filesystem)
    monkeypatch.setattr(os.path, "isfile", no_filesystem)
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=payload,
    ))
    assert result["message"] == "payload must be nonempty bytes"
    assert_failure(result, "VALIDATION")
    no_filesystem.assert_not_called()
    boundary.factory.assert_not_called()


@pytest.mark.parametrize("kind", ["missing", "directory", "empty", "unreadable"])
def test_local_file_failures_stop_before_http(boundary, monkeypatch, tmp_path, kind):
    path = tmp_path / "reference.png"
    if kind == "directory":
        path.mkdir()
    elif kind in {"empty", "unreadable"}:
        path.write_bytes(b"")
    if kind == "unreadable":
        monkeypatch.setattr("builtins.open", Mock(side_effect=OSError("cannot read image")))

    result = asyncio.run(boundary.client.upload_image(str(path), upload_name=UPLOAD_NAME))

    assert_failure(result, "VALIDATION")
    boundary.factory.assert_not_called()


@pytest.mark.parametrize("name", [None, *UNSAFE_NAMES])
def test_bad_server_name_fails_without_planned_name_fallback(boundary, name):
    boundary.response = httpx.Response(200, json={**RECEIPT, "name": name})
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert result["message"] == "Invalid image upload receipt: unsafe or missing name"
    assert_failure(result, "INVALID_RECEIPT")
    assert result["external_failure"]["external_call"]["receipt_violation"] == "IMAGE_RECEIPT_NAME_MISSING_OR_UNSAFE"
    boundary.factory.assert_called_once_with()
    boundary.post.assert_awaited_once()


@pytest.mark.parametrize("field, value", [
    *(('type', value) for value in [None, "", "output", "temp", "INPUT", 1, False, [], {}]),
    *(('subfolder', value) for value in [
        None, 1, False, [], {}, "/refs", "../refs", "refs/../escape", "refs/./child",
        "refs//child", "refs/", "refs\\child", "\\\\server\\refs", "C:refs", "C:/refs",
        "refs/.hidden", "refs/\x00child", "refs/\nchild", "refs/\x7fchild", "refs/\u53c2\u8003",
    ]),
])
def test_invalid_receipt_type_or_subfolder_fails_closed(boundary, field, value):
    boundary.response = httpx.Response(200, json={**RECEIPT, field: value})
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result, "INVALID_RECEIPT")
    assert field in result["message"]
    boundary.factory.assert_called_once_with()
    boundary.post.assert_awaited_once()


@pytest.mark.parametrize("field", ["name", "type", "subfolder"])
def test_missing_receipt_fields_fail_closed(boundary, field):
    boundary.response = httpx.Response(200, json={key: value for key, value in RECEIPT.items() if key != field})
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result, "INVALID_RECEIPT")
    assert field in result["message"]
    assert result["external_failure"]["external_call"]["response_excerpt"] is not None
    boundary.post.assert_awaited_once()


@pytest.mark.parametrize("response,failure_class", [
    (httpx.Response(201, json=RECEIPT), "HTTP_ERROR"),
    (httpx.Response(302, text="redirect"), "HTTP_ERROR"),
    (httpx.Response(500, json=RECEIPT), "HTTP_ERROR"),
    (httpx.Response(200, text="not JSON"), "INVALID_RESPONSE"),
    (httpx.Response(200, text="null"), "INVALID_RESPONSE"),
    (httpx.Response(200, json=[]), "INVALID_RESPONSE"),
    (httpx.Response(200, json="not an object"), "INVALID_RESPONSE"),
    (httpx.Response(200, json={}), "INVALID_RECEIPT"),
])
def test_failed_http_or_malformed_receipt_stops_without_retry(boundary, response, failure_class):
    boundary.response = response
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result, failure_class)
    boundary.factory.assert_called_once_with()
    boundary.post.assert_awaited_once()


@pytest.mark.parametrize("error,failure_class", [
    (httpx.ConnectError("offline"), "CONNECTION"),
    (httpx.ReadTimeout("timed out"), "TIMEOUT"),
])
def test_transport_failure_is_structured_without_retry(boundary, error, failure_class):
    boundary.error = error
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result, failure_class)
    assert result["message"] == f"Image upload failed: {str(error)}"
    boundary.factory.assert_called_once_with()
    boundary.post.assert_awaited_once()


def test_http_503_preserves_body_identity_but_bounds_and_redacts_excerpt(boundary):
    boundary.response = httpx.Response(503, json={
        "error": "temporarily unavailable",
        "authorization": "Bearer body-secret",
        "nested": {"api_token": "token-secret", "password": "password-secret"},
        "payload": "A" * 20000,
    })
    expected_body = boundary.response.content

    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))

    assert result["message"] == "Image upload failed (HTTP 503)"
    assert_failure(result, "HTTP_ERROR")
    call = result["external_failure"]["external_call"]
    assert call["http_status"] == 503
    assert call["response_body_sha256"] == hashlib.sha256(expected_body).hexdigest()
    assert call["response_body_bytes"] == len(expected_body)
    assert call["response_content_type"] == "application/json"
    assert len(call["response_excerpt"].encode()) <= 8 * 1024
    assert "temporarily unavailable" not in call["response_excerpt"]
    assert "[TEXT_RESPONSE_OMITTED" in call["response_excerpt"]
    assert "body-secret" not in call["response_excerpt"]
    assert "token-secret" not in call["response_excerpt"]
    assert "password-secret" not in call["response_excerpt"]
    assert "A" * 128 not in call["response_excerpt"]


def test_authorization_token_canary_is_removed_but_http_facts_remain(boundary):
    body = b"upstream denied request\nAuthorization: Token STAGE_A_AUTH_CANARY_9465"
    boundary.response = httpx.Response(503, content=body, headers={"content-type": "text/plain"})
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result, "HTTP_ERROR")
    diagnostic = result["external_failure"]
    call = diagnostic["external_call"]
    assert call["http_status"] == 503
    assert call["response_body_bytes"] == len(body)
    assert call["response_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert call["response_content_type"] == "text/plain"
    assert "STAGE_A_AUTH_CANARY_9465" not in json.dumps(diagnostic)
    assert diagnostic["redacted"] is True and diagnostic["truncated"] is True


def test_invalid_receipt_redacts_windows_absolute_path(boundary):
    receipt = {"name": r"C:\ComfyUI\private-project\reference.png", "subfolder": "", "type": "input"}
    boundary.response = httpx.Response(200, json=receipt)
    body = boundary.response.content
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result, "INVALID_RECEIPT")
    call = result["external_failure"]["external_call"]
    assert call["http_status"] == 200
    assert call["response_body_bytes"] == len(body)
    assert call["response_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert r"C:\ComfyUI\private-project\reference.png" not in call["response_excerpt"]
    assert "[LOCAL_PATH]" in call["response_excerpt"]


def test_malformed_json_is_invalid_response_with_full_body_evidence(boundary):
    boundary.response = httpx.Response(200, content=b'{"broken":', headers={"content-type": "application/json"})
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result, "INVALID_RESPONSE")
    call = result["external_failure"]["external_call"]
    assert call["response_body_sha256"] == hashlib.sha256(b'{"broken":').hexdigest()
    assert call["response_body_bytes"] == len(b'{"broken":')
    assert call["response_excerpt"] == "[MALFORMED_JSON_OMITTED]"


def test_excessively_nested_json_is_invalid_response_not_unknown(boundary):
    response = Mock(status_code=200, content=b"[[[[too deep]]]]", headers={"content-type": "application/json"})
    response.json.side_effect = RecursionError("maximum JSON depth exceeded")
    boundary.response = response
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result, "INVALID_RESPONSE")
    call = result["external_failure"]["external_call"]
    assert call["http_status"] == 200
    assert call["response_body_sha256"] == hashlib.sha256(response.content).hexdigest()


def test_httpx_decoding_error_is_invalid_response_not_unknown(boundary):
    boundary.error = httpx.DecodingError("invalid compressed response")
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result, "INVALID_RESPONSE")
    assert result["external_failure"]["external_call"]["exception_type"] == "DecodingError"


@pytest.mark.parametrize("mode", ["legacy", "snapshot", "file"])
def test_upload_preserves_cancellation(boundary, tmp_path, mode):
    path = tmp_path / "reference.png"
    path.write_bytes(PAYLOAD)
    options = {} if mode == "legacy" else {"upload_name": UPLOAD_NAME}
    if mode == "snapshot":
        options["payload"] = PAYLOAD
    boundary.error = asyncio.CancelledError("cancel upload")

    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(boundary.client.upload_image(str(path), **options))

    assert caught.value is boundary.error
    boundary.post.assert_awaited_once()


def test_frozen_client_code_and_legacy_branch_preserve_baseline_hashes():
    source = CLIENT_PATH.read_text(encoding="utf-8")
    cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef))
    methods = {node.name: node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    upload = methods["upload_image"]
    lines = source.splitlines(keepends=True)
    frozen = "".join(lines[:upload.lineno - 1] + lines[upload.end_lineno:])

    # Captured before this change; every byte outside upload_image remains frozen.
    assert hashlib.sha256(frozen.encode()).hexdigest() == "34a0f48fba06333321f6986357120e43d710b72da33acb960304486dcdb5f23b"
    assert hashlib.sha256(ast.get_source_segment(source, upload.body[-1]).encode()).hexdigest() == (
        "351fcf9aecf4b36d2566817dad1373dfe718e5b3894baefb9322012f91da35be"
    )
    for name, expected in {
        "upload_audio": "636a5e03ca0cbb20e24940a686a747372ba7acac4ffbf5f3ac86519335bada40",
        "queue_prompt": "0940a9cdddc88b966de8fac772008b367f050bbc0206d1d4249086ab02beb799",
    }.items():
        assert hashlib.sha256(ast.get_source_segment(source, methods[name]).encode()).hexdigest() == expected
