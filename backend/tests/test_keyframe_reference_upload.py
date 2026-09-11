"""Standalone client tests: Python 3.11, --noconftest, no app startup or network."""

import ast
import asyncio
from contextlib import asynccontextmanager
import hashlib
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, mock_open

import httpx
import pytest


CLIENT_PATH = Path(__file__).resolve().parents[1] / "app/services/comfyui/client.py"
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
    spec = importlib.util.spec_from_file_location("_keyframe_upload_client", CLIENT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.ComfyUIClient, "base_url", property(lambda self: "http://comfyui.test"))
    state = SimpleNamespace(
        client=module.ComfyUIClient(),
        response=httpx.Response(200, json=RECEIPT),
        error=None,
        calls=[],
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


def assert_failure(result):
    assert set(result) == {"success", "message"}
    assert result["success"] is False
    assert isinstance(result["message"], str) and result["message"]


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
    assert result == {"success": False, "message": "payload requires upload_name"}
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
    assert result == {"success": False, "message": "Invalid upload_name: expected a safe ASCII basename"}
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
    assert result == {"success": False, "message": "payload must be nonempty bytes"}
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

    assert_failure(result)
    boundary.factory.assert_not_called()


@pytest.mark.parametrize("name", [None, *UNSAFE_NAMES])
def test_bad_server_name_fails_without_planned_name_fallback(boundary, name):
    boundary.response = httpx.Response(200, json={**RECEIPT, "name": name})
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert result == {"success": False, "message": "Invalid image upload receipt: unsafe or missing name"}
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
    assert_failure(result)
    assert field in result["message"]
    boundary.factory.assert_called_once_with()
    boundary.post.assert_awaited_once()


@pytest.mark.parametrize("field", ["name", "type", "subfolder"])
def test_missing_receipt_fields_fail_closed(boundary, field):
    boundary.response = httpx.Response(200, json={key: value for key, value in RECEIPT.items() if key != field})
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result)
    assert field in result["message"]
    boundary.post.assert_awaited_once()


@pytest.mark.parametrize("response", [
    httpx.Response(201, json=RECEIPT),
    httpx.Response(302, text="redirect"),
    httpx.Response(500, json=RECEIPT),
    httpx.Response(200, text="not JSON"),
    httpx.Response(200, text="null"),
    httpx.Response(200, json=[]),
    httpx.Response(200, json="not an object"),
    httpx.Response(200, json={}),
])
def test_failed_http_or_malformed_receipt_stops_without_retry(boundary, response):
    boundary.response = response
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result)
    boundary.factory.assert_called_once_with()
    boundary.post.assert_awaited_once()


@pytest.mark.parametrize("error", [httpx.ConnectError("offline"), httpx.ReadTimeout("timed out")])
def test_transport_failure_is_structured_without_retry(boundary, error):
    boundary.error = error
    result = asyncio.run(boundary.client.upload_image(
        "missing.png", upload_name=UPLOAD_NAME, payload=PAYLOAD,
    ))
    assert_failure(result)
    boundary.factory.assert_called_once_with()
    boundary.post.assert_awaited_once()


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
