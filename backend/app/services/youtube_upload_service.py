"""OAuth and serial, resumable YouTube uploads for merged novel videos."""
import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

from app.core.database import SessionLocal
from app.core.security import decrypt_value, encrypt_value
from app.models.task import Task
from app.models.system_config import SystemConfig
from app.models.youtube_config import YoutubeConfig
from app.services.background_workers import persistent_job, worker_manager
from app.services.file_storage import file_storage
from app.utils.path_utils import url_to_local_path
from app.utils.time_utils import format_datetime


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_or_create_config(db):
    config = db.get(YoutubeConfig, "default")
    if config is None:
        config = YoutubeConfig(id="default")
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def configured_proxy_url(db) -> str:
    """Use only the YouTube switch in the central system configuration."""
    config = db.get(SystemConfig, "default")
    return (config.youtube_proxy_url or "") if config and config.youtube_proxy_enabled else ""


def public_settings(config: YoutubeConfig, default_redirect_uri: str) -> dict:
    return {
        "clientId": config.client_id or "",
        "hasClientSecret": bool(config.client_secret_encrypted),
        "connected": bool(config.token_encrypted),
        "redirectUri": config.redirect_uri or default_redirect_uri,
        "defaultTags": config.default_tags or "",
    }


def save_client_file(config: YoutubeConfig, contents: bytes) -> None:
    if len(contents) > 1024 * 1024:
        raise ValueError("OAuth 配置文件不能超过 1 MB")
    try:
        parsed = json.loads(contents.decode("utf-8-sig"))
        client = parsed.get("web") or parsed.get("installed")
        client_id = str(client["client_id"]).strip()
        client_secret = str(client["client_secret"]).strip()
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("请选择有效的 Google OAuth client_secret.json") from exc
    if not client_id or not client_secret:
        raise ValueError("OAuth 文件缺少 Client ID 或 Client secret")
    config.client_id = client_id
    config.client_secret_encrypted = encrypt_value(client_secret)
    config.token_encrypted = ""
    config.oauth_state = ""


def authorization_url(db, config: YoutubeConfig, redirect_uri: str) -> str:
    if not config.client_id or not config.client_secret_encrypted:
        raise ValueError("请先配置 Google OAuth Client ID 和 Client secret")
    config.oauth_state = secrets.token_urlsafe(32)
    config.oauth_state_created_at = datetime.utcnow()
    db.commit()
    query = urlencode({
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": config.oauth_state,
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def finish_authorization(db, config: YoutubeConfig, code: str, state: str, redirect_uri: str) -> None:
    created = config.oauth_state_created_at
    if not state or not secrets.compare_digest(state, config.oauth_state or "") or not created or datetime.utcnow() - created > timedelta(minutes=10):
        raise ValueError("OAuth state 无效或已过期，请重新授权")
    config.oauth_state = ""
    config.oauth_state_created_at = None
    db.commit()
    proxy = configured_proxy_url(db) or None
    with httpx.Client(proxies=proxy, timeout=60, trust_env=False) as client:
        response = client.post(TOKEN_URL, data={
            "code": code,
            "client_id": config.client_id,
            "client_secret": decrypt_value(config.client_secret_encrypted),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        response.raise_for_status()
        token = response.json()
    if not token.get("access_token") or not token.get("refresh_token"):
        raise ValueError("Google 未返回长期授权令牌，请重新授权并同意离线访问")
    token_data = {
        "token": token["access_token"],
        "refresh_token": token["refresh_token"],
        "token_uri": TOKEN_URL,
        "client_id": config.client_id,
        "client_secret": decrypt_value(config.client_secret_encrypted),
        "scopes": SCOPES,
        "expiry": (datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 3600)))).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    config.token_encrypted = encrypt_value(json.dumps(token_data))
    db.commit()


def _youtube_client():
    try:
        import httplib2
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("缺少 YouTube 上传依赖，请安装后端 requirements.txt") from exc
    with SessionLocal() as db:
        config = get_or_create_config(db)
        if not config.token_encrypted:
            raise RuntimeError("请先连接 YouTube 账号")
        token_data = json.loads(decrypt_value(config.token_encrypted))
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        proxy_url = configured_proxy_url(db)
        if creds.expired and creds.refresh_token:
            import requests
            session = requests.Session()
            session.trust_env = False
            if proxy_url:
                session.proxies.update({"http": proxy_url, "https": proxy_url})
            creds.refresh(Request(session=session))
            config.token_encrypted = encrypt_value(creds.to_json())
            db.commit()
    if not creds.valid:
        raise RuntimeError("YouTube 授权已失效，请重新授权")
    proxy_info = None
    if proxy_url:
        parsed = urlparse(proxy_url)
        if parsed.scheme != "http" or not parsed.hostname or not parsed.port:
            raise RuntimeError("YouTube 代理地址必须是包含主机和端口的 http:// 地址")
        try:
            import socks
        except ImportError as exc:
            raise RuntimeError("启用 YouTube 代理需要 PySocks，请安装后端 requirements.txt") from exc
        proxy_info = httplib2.ProxyInfo(
            proxy_type=socks.PROXY_TYPE_HTTP,
            proxy_host=parsed.hostname,
            proxy_port=parsed.port,
            proxy_user=parsed.username,
            proxy_pass=parsed.password,
        )
    http = httplib2.Http(proxy_info=proxy_info)
    http.follow_redirects = False  # YouTube chunk acknowledgements return HTTP 308.
    return build("youtube", "v3", http=AuthorizedHttp(creds, http=http), cache_discovery=False)


def list_playlists() -> list[dict]:
    youtube = _youtube_client()
    items = []
    page_token = None
    while True:
        result = youtube.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=page_token).execute()
        items.extend({"id": row["id"], "title": row.get("snippet", {}).get("title", "")} for row in result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            return items


def format_upload(task: Task | None) -> dict | None:
    if task is None:
        return None
    metadata = json.loads(task.metadata_json or "{}")
    return {
        "id": task.id, "status": task.status, "progress": task.progress or 0,
        "currentStep": task.current_step, "errorMessage": task.error_message,
        "title": metadata.get("title", ""), "privacyStatus": metadata.get("privacy_status", "private"),
        "youtubeUrl": task.result_url, "warnings": metadata.get("warnings", []),
        "createdAt": format_datetime(task.created_at),
    }


def enqueue_upload(task_id: str) -> None:
    payload = {"task_id": task_id, "enqueue_attempt": secrets.token_hex(8)}
    worker_manager.worker("youtube_upload").enqueue(persistent_job(
        task_id, "app.services.youtube_upload_service:run_upload", payload,
        lambda: run_upload(**payload),
    ))


def resume_active_uploads() -> int:
    with SessionLocal() as db:
        tasks = db.query(Task).filter(Task.type == "youtube_upload", Task.status.in_(["pending", "running"])).all()
        for task in tasks:
            task.status = "pending"
            task.current_step = "服务重启，等待恢复上传..."
        db.commit()
        ids = [task.id for task in tasks]
    for task_id in ids:
        enqueue_upload(task_id)
    return len(ids)


def _local_file(url: str, label: str) -> Path:
    local = url_to_local_path(url)
    path = Path(local).resolve() if local else None
    if not path or not path.is_relative_to(file_storage.base_dir.resolve()) or not path.is_file():
        raise RuntimeError(f"{label}文件不存在")
    return path


def _run_upload_sync(task_id: str) -> None:
    from googleapiclient.http import MediaFileUpload

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task or task.status not in {"pending", "running"}:
            return
        metadata = json.loads(task.metadata_json or "{}")
        merge = db.get(Task, task.parent_task_id)
        cover = db.get(Task, metadata.get("cover_id"))
        if not merge or merge.status != "completed" or not merge.result_url:
            raise RuntimeError("已完成的合并视频不存在")
        if not cover or cover.status != "completed" or cover.parent_task_id != merge.id or json.loads(cover.metadata_json or "{}").get("aspect_ratio") != "16:9":
            raise RuntimeError("已生成的 16:9 视频封面不存在")
        video_path = _local_file(merge.result_url, "视频")
        cover_path = _local_file(cover.result_url, "封面")
        task.status = "running"
        task.started_at = task.started_at or datetime.utcnow()
        task.current_step = "正在连接 YouTube..."
        db.commit()

    youtube = _youtube_client()
    video_id = metadata.get("youtube_video_id")
    if not video_id:
        body = {
            "snippet": {
                "title": metadata["title"], "description": metadata.get("description", ""),
                "tags": metadata.get("tags", []), "categoryId": "22",
                "defaultLanguage": "zh", "defaultAudioLanguage": "zh",
            },
            "status": {
                "privacyStatus": metadata["privacy_status"],
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": True,
            },
        }
        media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                with SessionLocal() as db:
                    task = db.get(Task, task_id)
                    task.progress = 5 + int(status.progress() * 75)
                    task.current_step = "正在上传视频..."
                    db.commit()
        video_id = str(response.get("id") or "")
        if not video_id:
            raise RuntimeError("YouTube 未返回视频 ID")
        metadata["youtube_video_id"] = video_id
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            task.result_url = f"https://youtu.be/{video_id}"
            task.progress = 85
            task.current_step = "视频已上传，正在设置封面和播放列表..."
            task.metadata_json = json.dumps(metadata, ensure_ascii=False)
            db.commit()

    warnings = []
    if not metadata.get("thumbnail_done"):
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(cover_path), mimetype="image/png")).execute()
            metadata["thumbnail_done"] = True
            with SessionLocal() as db:
                task = db.get(Task, task_id)
                task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                db.commit()
        except Exception as exc:
            warnings.append(f"封面上传失败：{exc}")
    if metadata.get("playlist_id") and not metadata.get("playlist_done"):
        try:
            youtube.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": metadata["playlist_id"],
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }}).execute()
            metadata["playlist_done"] = True
            with SessionLocal() as db:
                task = db.get(Task, task_id)
                task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                db.commit()
        except Exception as exc:
            warnings.append(f"加入播放列表失败：{exc}")
    metadata["warnings"] = warnings
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.status = "completed"
        task.progress = 100
        task.current_step = "上传完成" if not warnings else "视频已上传，附加操作有警告"
        task.completed_at = datetime.utcnow()
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()


async def run_upload(task_id: str, enqueue_attempt: str | None = None) -> None:
    try:
        await asyncio.to_thread(_run_upload_sync, task_id)
    except Exception as exc:
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            if task:
                task.status = "failed"
                task.error_message = str(exc)
                task.current_step = "上传失败"
                db.commit()
