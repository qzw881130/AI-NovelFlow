"""YouTube settings, OAuth, playlists and merged-video uploads."""
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import encrypt_value
from app.models.novel import Novel
from app.models.task import Task
from app.services.file_storage import file_storage
from app.services.youtube_upload_service import (
    authorization_url, enqueue_upload, finish_authorization, format_upload,
    get_or_create_config, list_playlists, public_settings, save_client_file,
)
from app.utils.path_utils import url_to_local_path


router = APIRouter()


class YoutubeSettingsUpdate(BaseModel):
    clientId: str | None = None
    clientSecret: str | None = None
    redirectUri: str | None = None
    defaultTags: str | None = None


class YoutubeUploadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: str = Field(default="", max_length=500)
    privacyStatus: Literal["private", "unlisted", "public"] = "private"
    playlistId: str = Field(default="", max_length=100)
    coverId: str | None = None


def _redirect_uri(request: Request, config) -> str:
    return config.redirect_uri or str(request.url_for("youtube_oauth_callback"))


def _safe_local_file(url: str) -> bool:
    local = url_to_local_path(url)
    path = Path(local).resolve() if local else None
    return bool(path and path.is_relative_to(file_storage.base_dir.resolve()) and path.is_file())


@router.get("/youtube/settings")
def get_youtube_settings(request: Request, db: Session = Depends(get_db)):
    config = get_or_create_config(db)
    return {"success": True, "data": public_settings(config, str(request.url_for("youtube_oauth_callback")))}


@router.post("/youtube/settings")
def save_youtube_settings(request: Request, payload: YoutubeSettingsUpdate, db: Session = Depends(get_db)):
    config = get_or_create_config(db)
    if payload.clientId is not None and payload.clientId.strip() != config.client_id:
        config.client_id = payload.clientId.strip()
        config.token_encrypted = ""
    if payload.clientSecret and payload.clientSecret.strip():
        config.client_secret_encrypted = encrypt_value(payload.clientSecret.strip())
        config.token_encrypted = ""
    if payload.redirectUri is not None:
        uri = payload.redirectUri.strip()
        if uri and not uri.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Redirect URI 必须是 http 或 https 地址")
        if uri and not uri.endswith("/api/youtube/oauth/callback"):
            raise HTTPException(status_code=400, detail="Redirect URI 必须指向本服务的 /api/youtube/oauth/callback")
        config.redirect_uri = uri
    if payload.defaultTags is not None:
        config.default_tags = payload.defaultTags.strip()
    db.commit()
    return {"success": True, "data": public_settings(config, str(request.url_for("youtube_oauth_callback")))}


@router.post("/youtube/client-file")
async def upload_youtube_client_file(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    config = get_or_create_config(db)
    try:
        save_client_file(config, await file.read(1024 * 1024 + 1))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"success": True, "data": public_settings(config, str(request.url_for("youtube_oauth_callback")))}


@router.get("/youtube/auth-url")
def get_youtube_auth_url(request: Request, db: Session = Depends(get_db)):
    config = get_or_create_config(db)
    try:
        url = authorization_url(db, config, _redirect_uri(request, config))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": {"url": url}}


@router.get("/youtube/oauth/callback", name="youtube_oauth_callback")
def youtube_oauth_callback(request: Request, code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    success = False
    if error:
        message = "Google 授权被取消或拒绝"
    else:
        try:
            config = get_or_create_config(db)
            finish_authorization(db, config, code, state, _redirect_uri(request, config))
            message = "YouTube 授权成功，可以关闭此窗口。"
            success = True
        except Exception as exc:
            message = f"YouTube 授权失败：{exc}"
    # Do not echo the authorization code, state, or secrets in the callback page.
    import html
    script = "<script>if(window.opener){window.opener.postMessage('novelflow-youtube-oauth','*');window.close();}</script>" if success else ""
    return HTMLResponse(f"<!doctype html><html lang='zh'><meta charset='utf-8'><title>YouTube 授权</title><body><p>{html.escape(message)}</p>{script}</body></html>")


@router.get("/youtube/playlists")
def get_youtube_playlists():
    try:
        return {"success": True, "data": list_playlists()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/video-merges/{merge_id}/youtube-upload")
async def create_youtube_upload(novel_id: str, merge_id: str, payload: YoutubeUploadRequest, db: Session = Depends(get_db)):
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    merge = db.query(Task).filter(
        Task.id == merge_id, Task.novel_id == novel_id,
        Task.type == "novel_video", Task.status == "completed",
    ).first()
    if not novel or not merge or not merge.result_url or not _safe_local_file(merge.result_url):
        raise HTTPException(status_code=404, detail="已完成的合并视频文件不存在")
    config = get_or_create_config(db)
    if not config.token_encrypted:
        raise HTTPException(status_code=400, detail="请先连接 YouTube 账号")
    active = db.query(Task).filter(
        Task.type == "youtube_upload", Task.parent_task_id == merge_id,
        Task.status.in_(["pending", "running"]),
    ).first()
    if active:
        enqueue_upload(active.id)
        return {"success": True, "data": format_upload(active)}
    cover_query = db.query(Task).filter(
        Task.type == "novel_video_cover", Task.novel_id == novel_id,
        Task.parent_task_id == merge_id, Task.status == "completed",
    )
    if payload.coverId:
        cover_query = cover_query.filter(Task.id == payload.coverId)
    covers = cover_query.order_by(Task.created_at.desc(), Task.id.desc()).all()
    cover = next((item for item in covers if item.result_url and json.loads(item.metadata_json or "{}").get("aspect_ratio") == "16:9" and _safe_local_file(item.result_url)), None)
    if not cover:
        raise HTTPException(status_code=400, detail="请先生成并完成此视频的 16:9 封面")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="视频标题不能为空")
    upload = Task(
        type="youtube_upload", status="pending", progress=0,
        name=f"上传 YouTube: {title}", novel_id=novel_id,
        parent_task_id=merge_id, current_step="等待上传...",
        metadata_json=json.dumps({
            "title": title, "description": payload.description.strip(),
            "tags": [tag.strip() for tag in payload.tags.replace("，", ",").split(",") if tag.strip()],
            "privacy_status": payload.privacyStatus, "playlist_id": payload.playlistId.strip(),
            "cover_id": cover.id,
        }, ensure_ascii=False),
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    enqueue_upload(upload.id)
    return {"success": True, "data": format_upload(upload)}


@router.post("/youtube/uploads/{task_id}/retry")
async def retry_youtube_upload(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id, Task.type == "youtube_upload").first()
    if not task:
        raise HTTPException(status_code=404, detail="上传任务不存在")
    metadata = json.loads(task.metadata_json or "{}")
    if task.status != "failed" and not (task.status == "completed" and metadata.get("warnings")):
        raise HTTPException(status_code=400, detail="仅失败或有警告的上传任务可重试")
    task.status = "pending"
    task.error_message = None
    task.current_step = "等待重试..."
    task.progress = 85 if task.result_url else 0
    db.commit()
    enqueue_upload(task.id)
    return {"success": True, "data": format_upload(task)}
