"""YouTube upload must use the generated 16:9 cover and survive task refreshes."""
import asyncio
import json
import sys
import types
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import sessionmaker

from app.models.novel import Novel
from app.models.task import Task
from app.models.system_config import SystemConfig
from app.models.youtube_config import YoutubeConfig
from app.models.background_job import BackgroundJob
from app.api.config import get_or_create_config as get_or_create_system_config
from app.services.background_workers import WorkerManager, persistent_job
from app.services import youtube_upload_service as service


def test_upload_requires_existing_16x9_cover_and_snapshots_it(client, db_session, monkeypatch):
    novel = Novel(title="药", author="鲁迅")
    db_session.add(novel)
    db_session.flush()
    merge = Task(type="novel_video", status="completed", novel_id=novel.id,
                 name="合并", result_url="/api/files/video.mp4", metadata_json="{}")
    four_three = Task(type="novel_video_cover", status="completed", novel_id=novel.id,
                      parent_task_id=merge.id, name="4:3", result_url="/api/files/4x3.png",
                      metadata_json=json.dumps({"aspect_ratio": "4:3"}))
    config = YoutubeConfig(id="default", client_id="test", token_encrypted="fake")
    db_session.add_all([merge, four_three, config])
    db_session.commit()
    monkeypatch.setattr("app.api.youtube._safe_local_file", lambda _: True)
    queued = []
    def enqueue_in_request_loop(task_id):
        asyncio.get_running_loop()
        queued.append(task_id)
    monkeypatch.setattr("app.api.youtube.enqueue_upload", enqueue_in_request_loop)
    endpoint = f"/api/novels/{novel.id}/video-merges/{merge.id}/youtube-upload"
    payload = {"title": "药", "privacyStatus": "private", "tags": "小说,有声小说"}
    assert client.post(endpoint, json=payload).status_code == 400

    wide = Task(type="novel_video_cover", status="completed", novel_id=novel.id,
                parent_task_id=merge.id, name="16:9", result_url="/api/files/16x9.png",
                metadata_json=json.dumps({"aspect_ratio": "16:9"}))
    db_session.add(wide)
    db_session.commit()
    response = client.post(endpoint, json=payload)
    assert response.status_code == 200, response.text
    upload = db_session.query(Task).filter(Task.type == "youtube_upload").one()
    assert queued == [upload.id]
    assert json.loads(upload.metadata_json)["cover_id"] == wide.id
    assert json.loads(upload.metadata_json)["tags"] == ["小说", "有声小说"]
    assert client.post(endpoint, json=payload).json()["data"]["id"] == upload.id
    assert queued == [upload.id, upload.id]
    history = client.get(f"/api/novels/{novel.id}/video-merges").json()["data"]
    assert history[0]["youtubeUpload"]["id"] == upload.id


def test_retry_upload_schedules_from_event_loop(client, db_session, monkeypatch):
    upload = Task(type="youtube_upload", status="failed", name="upload", metadata_json="{}")
    db_session.add(upload)
    db_session.commit()
    queued = []
    def enqueue_in_request_loop(task_id):
        asyncio.get_running_loop()
        queued.append(task_id)
    monkeypatch.setattr("app.api.youtube.enqueue_upload", enqueue_in_request_loop)
    response = client.post(f"/api/youtube/uploads/{upload.id}/retry")
    assert response.status_code == 200, response.text
    assert db_session.get(Task, upload.id).status == "pending"
    assert queued == [upload.id]


def test_retry_uses_new_persistent_job_identity(db_engine, db_session):
    manager = WorkerManager(session_factory=sessionmaker(bind=db_engine))
    task = Task(type="youtube_upload", status="pending", name="upload")
    db_session.add(task)
    db_session.commit()
    handler = "app.services.youtube_upload_service:run_upload"
    first = manager.persist(persistent_job(task.id, handler, {"task_id": task.id, "enqueue_attempt": "first"}, lambda: None), "youtube_upload")
    job = db_session.get(BackgroundJob, first)
    job.status = "completed"
    db_session.commit()
    second = manager.persist(persistent_job(task.id, handler, {"task_id": task.id, "enqueue_attempt": "second"}, lambda: None), "youtube_upload")
    assert second != first


def test_settings_never_return_secrets(client):
    response = client.post("/api/youtube/settings", json={
        "clientId": "id", "clientSecret": "very-private", "defaultTags": "tag",
    })
    assert response.status_code == 200
    assert "very-private" not in response.text
    assert response.json()["data"]["hasClientSecret"] is True
    assert "very-private" not in client.get("/api/youtube/settings").text


def test_youtube_proxy_is_controlled_only_by_system_settings(client, db_session):
    response = client.post("/api/config/", json={"proxy": {
        "enabled": False, "httpProxy": "http://127.0.0.1:7890",
        "httpsProxy": "http://127.0.0.1:7890", "youtubeEnabled": True,
        "youtubeProxyUrl": "http://192.168.50.2:7897",
    }})
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    data = client.get("/api/config/").json()["data"]
    assert data["proxyEnabled"] is False
    assert data["youtubeProxyEnabled"] is True
    assert data["youtubeProxyUrl"] == "http://192.168.50.2:7897"
    assert service.configured_proxy_url(db_session) == "http://192.168.50.2:7897"
    assert "proxyEnabled" not in client.get("/api/youtube/settings").json()["data"]

    response = client.post("/api/config/", json={"proxy": {
        "enabled": True, "httpProxy": "http://127.0.0.1:7890",
        "httpsProxy": "http://127.0.0.1:7890", "youtubeEnabled": False,
        "youtubeProxyUrl": "http://192.168.50.2:7897",
    }})
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert service.configured_proxy_url(db_session) == ""
    assert db_session.get(SystemConfig, "default").proxy_enabled is True


def test_legacy_youtube_proxy_moves_to_system_settings_once(db_engine, db_session):
    db_session.add(YoutubeConfig(id="default", proxy_enabled=True, proxy_url="http://127.0.0.1:7897"))
    db_session.commit()
    with db_engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE system_configs DROP COLUMN youtube_proxy_enabled")
        connection.exec_driver_sql("ALTER TABLE system_configs DROP COLUMN youtube_proxy_url")

    config = get_or_create_system_config(db_session)
    assert config.youtube_proxy_enabled is True
    assert config.youtube_proxy_url == "http://127.0.0.1:7897"
    config.youtube_proxy_enabled = False
    db_session.commit()
    assert get_or_create_system_config(db_session).youtube_proxy_enabled is False


def test_oauth_callback_requires_matching_state(client, db_session, monkeypatch):
    contents = json.dumps({"web": {"client_id": "client-id", "client_secret": "client-secret"}})
    response = client.post("/api/youtube/client-file", files={"file": ("client_secret.json", contents, "application/json")})
    assert response.status_code == 200
    assert "client-secret" not in response.text
    auth_url = client.get("/api/youtube/auth-url").json()["data"]["url"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    assert "无效" in client.get("/api/youtube/oauth/callback", params={"code": "code", "state": "wrong"}).text
    assert not db_session.get(YoutubeConfig, "default").token_encrypted

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, data):
            assert data["redirect_uri"].endswith("/api/youtube/oauth/callback")
            return Response()
    monkeypatch.setattr(service.httpx, "Client", Client)
    success = client.get("/api/youtube/oauth/callback", params={"code": "code", "state": state})
    assert "授权成功" in success.text
    assert client.get("/api/youtube/settings").json()["data"]["connected"] is True


def test_upload_worker_sets_png_thumbnail_and_playlist(db_engine, monkeypatch, tmp_path):
    session_factory = sessionmaker(bind=db_engine)
    monkeypatch.setattr(service, "SessionLocal", session_factory)
    video = tmp_path / "video.mp4"
    cover_file = tmp_path / "cover.png"
    video.write_bytes(b"video")
    cover_file.write_bytes(b"png")
    monkeypatch.setattr(service, "_local_file", lambda url, label: video if label == "视频" else cover_file)
    media = types.ModuleType("googleapiclient.http")
    media.MediaFileUpload = lambda path, **kwargs: {"path": path, **kwargs}
    monkeypatch.setitem(sys.modules, "googleapiclient", types.ModuleType("googleapiclient"))
    monkeypatch.setitem(sys.modules, "googleapiclient.http", media)

    calls = []
    class Request:
        def next_chunk(self):
            return None, {"id": "video-123"}
        def execute(self):
            return {}
    class Resource:
        def __init__(self, kind): self.kind = kind
        def insert(self, **kwargs):
            calls.append((self.kind, kwargs))
            return Request()
        def set(self, **kwargs):
            calls.append((self.kind, kwargs))
            return Request()
    class Youtube:
        def videos(self): return Resource("video")
        def thumbnails(self): return Resource("thumbnail")
        def playlistItems(self): return Resource("playlist")
    monkeypatch.setattr(service, "_youtube_client", lambda: Youtube())

    with session_factory() as db:
        merge = Task(type="novel_video", status="completed", name="merge", result_url="/api/files/video.mp4")
        db.add(merge)
        db.flush()
        cover = Task(type="novel_video_cover", status="completed", name="cover",
                     parent_task_id=merge.id, result_url="/api/files/cover.png",
                     metadata_json=json.dumps({"aspect_ratio": "16:9"}))
        db.add(cover)
        db.flush()
        upload = Task(type="youtube_upload", status="pending", name="upload", parent_task_id=merge.id,
                      metadata_json=json.dumps({"title": "药", "cover_id": cover.id,
                                                "privacy_status": "private", "playlist_id": "playlist-123"}))
        db.add(upload)
        db.commit()
        upload_id = upload.id

    service._run_upload_sync(upload_id)
    with session_factory() as db:
        result = db.get(Task, upload_id)
        assert result.status == "completed"
        assert result.result_url == "https://youtu.be/video-123"
        assert json.loads(result.metadata_json)["thumbnail_done"] is True
        assert json.loads(result.metadata_json)["playlist_done"] is True
    assert [kind for kind, _ in calls] == ["video", "thumbnail", "playlist"]
    assert calls[1][1]["media_body"]["mimetype"] == "image/png"
