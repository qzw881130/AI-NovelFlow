"""Video seeking must return the exact requested bytes through the file API."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import files


@pytest.fixture
def media_client(tmp_path, monkeypatch):
    monkeypatch.setattr(files.file_storage, "base_dir", tmp_path)
    (tmp_path / "preview.mp4").write_bytes(b"0123456789")
    (tmp_path / "empty.mp4").write_bytes(b"")
    app = FastAPI()
    app.include_router(files.router, prefix="/api/files")
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("byte_range, expected, content_range", [
    ("bytes=3-6", b"3456", "bytes 3-6/10"),
    ("bytes=7-", b"789", "bytes 7-9/10"),
    ("bytes=-3", b"789", "bytes 7-9/10"),
    ("bytes=7-999", b"789", "bytes 7-9/10"),
    ("bytes=-999", b"0123456789", "bytes 0-9/10"),
    ("bytes=0-0", b"0", "bytes 0-0/10"),
])
def test_video_seek_returns_partial_content(media_client, byte_range, expected, content_range):
    response = media_client.get("/api/files/preview.mp4", headers={"Range": byte_range})
    assert response.status_code == 206
    assert response.content == expected
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(expected))
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"


def test_full_download_and_head_remain_available(media_client):
    full = media_client.get("/api/files/preview.mp4")
    assert full.status_code == 200
    assert full.content == b"0123456789"
    assert full.headers["accept-ranges"] == "bytes"
    assert "content-range" not in full.headers
    head = media_client.head("/api/files/preview.mp4")
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == "10"
    assert head.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize("byte_range", ["bytes=10-", "bytes=6-3", "bytes=-0", "bytes=-", "bytes=bad"])
def test_invalid_ranges_report_file_size(media_client, byte_range):
    response = media_client.get("/api/files/preview.mp4", headers={"Range": byte_range})
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */10"
    assert response.content == b""


def test_empty_file_cannot_satisfy_range(media_client):
    response = media_client.get("/api/files/empty.mp4", headers={"Range": "bytes=0-"})
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */0"


def test_if_range_preserves_file_identity(media_client):
    full = media_client.get("/api/files/preview.mp4")
    for validator in (full.headers["etag"], full.headers["last-modified"]):
        partial = media_client.get("/api/files/preview.mp4", headers={
            "Range": "bytes=5-", "If-Range": validator,
        })
        assert partial.status_code == 206
        assert partial.content == b"56789"
        assert partial.headers["etag"] == full.headers["etag"]
    changed = media_client.get("/api/files/preview.mp4", headers={
        "Range": "bytes=5-", "If-Range": '"outdated-file"',
    })
    assert changed.status_code == 200
    assert changed.content == full.content


@pytest.mark.parametrize("byte_range", ["bytes=0-1,5-6", "items=0-1"])
def test_unsupported_ranges_fall_back_to_full_download(media_client, byte_range):
    response = media_client.get("/api/files/preview.mp4", headers={"Range": byte_range})
    assert response.status_code == 200
    assert response.content == b"0123456789"


def test_missing_files_still_return_404(media_client):
    assert media_client.get("/api/files/missing.mp4", headers={"Range": "bytes=0-"}).status_code == 404
