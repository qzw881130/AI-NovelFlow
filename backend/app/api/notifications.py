"""Independent notification configuration, tests and browser sound delivery API."""
import json
import re
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.notification import NotificationDelivery
from app.services.notification_channels import validate_feishu_webhook
from app.services.notification_registry import EVENT_REGISTRY, list_events
from app.services.notification_service import (
    SOUNDS, NotificationService, encrypt_secret, event_switches, get_or_create_settings, mask_secret,
)

router = APIRouter()


class PageSoundUpdate(BaseModel):
    enabled: bool
    soundId: str
    volume: float = Field(ge=0, le=1)


class FeishuUpdate(BaseModel):
    enabled: bool
    webhook: str | None = None
    secret: str | None = None


class TelegramUpdate(BaseModel):
    enabled: bool
    botToken: str | None = None
    chatId: str | None = None


class NotificationUpdate(BaseModel):
    pageSound: PageSoundUpdate | None = None
    feishu: FeishuUpdate | None = None
    telegram: TelegramUpdate | None = None
    eventSwitches: dict[str, bool] | None = None


class ChannelTest(BaseModel):
    channel: str


class EventTest(BaseModel):
    event_code: str
    payload: dict = Field(default_factory=dict)


_DEVELOPMENT_NETWORKS = tuple(ip_network(network) for network in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7",
))


def _private_frontend_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in _DEVELOPMENT_NETWORKS)


def _development_frontend_only(request: Request) -> None:
    """Use the existing Vite proxy/network boundary; reject direct LAN API and cross-site calls."""
    if not get_settings().DEBUG:
        raise HTTPException(status_code=403, detail="仅开发环境允许模拟事件")

    origin = request.headers.get("origin")
    if not origin or request.headers.get("sec-fetch-site") not in {None, "same-origin"}:
        raise HTTPException(status_code=403, detail="请从 NovelFlow 页面发送模拟事件")
    parsed_origin = None
    try:
        parsed_origin = urlsplit(origin)
        client = ip_address(request.client.host) if request.client else None
        same_origin = (
            parsed_origin.scheme == request.url.scheme
            and parsed_origin.netloc.lower() == request.url.netloc.lower()
            and not parsed_origin.username
            and not parsed_origin.password
        )
        local_connection = bool(client and client.is_loopback)
    except ValueError:
        same_origin = False
        local_connection = False

    if not same_origin or not _private_frontend_host(parsed_origin.hostname if parsed_origin else None):
        raise HTTPException(status_code=403, detail="模拟事件仅允许私有网络同源页面")

    # Vite runs beside the API and preserves the browser-visible Host. Its marker
    # is useful only together with the actual loopback socket, not on its own.
    from_frontend_proxy = request.headers.get("x-novelflow-frontend-proxy") == "1"
    direct_local_page = _private_frontend_host(request.url.hostname) and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
    if not local_connection or not (from_frontend_proxy or direct_local_page):
        raise HTTPException(status_code=403, detail="请通过 NovelFlow 前端访问模拟事件接口")


@router.get("/config")
def get_notification_config(db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    latest_id = db.query(func.max(NotificationDelivery.id)).filter(
        NotificationDelivery.channel == "PAGE_SOUND"
    ).scalar() or 0
    return {"success": True, "data": {
        "pageSound": {"enabled": settings.page_sound_enabled, "soundId": settings.sound_id, "volume": settings.volume},
        "feishu": {"enabled": settings.feishu_enabled, "webhookMasked": mask_secret(settings.feishu_webhook_encrypted),
                   "secretMasked": mask_secret(settings.feishu_secret_encrypted)},
        "telegram": {"enabled": settings.telegram_enabled, "botTokenMasked": mask_secret(settings.telegram_token_encrypted),
                     "chatIdMasked": mask_secret(settings.telegram_chat_id_encrypted)},
        "events": list_events(event_switches(settings)),
        "sounds": [{"id": code, "name": name, "url": f"/sounds/{code}.wav"} for code, name in SOUNDS.items()],
        "latestPageSoundId": latest_id,
    }}


@router.put("/config")
def update_notification_config(update: NotificationUpdate, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    if update.pageSound and update.pageSound.soundId not in SOUNDS:
        raise HTTPException(status_code=422, detail="未知提示音")
    if update.feishu:
        webhook = update.feishu.webhook
        if webhook and not validate_feishu_webhook(webhook):
            raise HTTPException(status_code=422, detail="请输入有效的飞书自定义机器人 HTTPS Webhook")
        if update.feishu.enabled and not (webhook or settings.feishu_webhook_encrypted):
            raise HTTPException(status_code=422, detail="开启飞书通知前请填写 Webhook")
        if update.feishu.enabled and webhook == "":
            raise HTTPException(status_code=422, detail="开启飞书通知时不能清空 Webhook")
    if update.telegram:
        token = update.telegram.botToken
        chat_id = update.telegram.chatId
        if token and not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
            raise HTTPException(status_code=422, detail="Bot Token 格式无效")
        if chat_id and not re.fullmatch(r"(?:-?\d+|@[A-Za-z0-9_]+)", chat_id):
            raise HTTPException(status_code=422, detail="Chat ID 格式无效")
        if update.telegram.enabled and (not (token or settings.telegram_token_encrypted) or not (chat_id or settings.telegram_chat_id_encrypted)):
            raise HTTPException(status_code=422, detail="开启 Telegram 通知前请填写 Bot Token 和 Chat ID")
        if update.telegram.enabled and (token == "" or chat_id == ""):
            raise HTTPException(status_code=422, detail="开启 Telegram 通知时不能清空凭据")
    if update.eventSwitches and any(code not in EVENT_REGISTRY for code in update.eventSwitches):
        raise HTTPException(status_code=422, detail="存在未注册的通知事件")

    try:
        if update.pageSound:
            settings.page_sound_enabled = update.pageSound.enabled
            settings.sound_id = update.pageSound.soundId
            settings.volume = update.pageSound.volume
        if update.feishu:
            settings.feishu_enabled = update.feishu.enabled
            if update.feishu.webhook is not None:
                settings.feishu_webhook_encrypted = encrypt_secret(update.feishu.webhook) if update.feishu.webhook else None
            if update.feishu.secret is not None:
                settings.feishu_secret_encrypted = encrypt_secret(update.feishu.secret) if update.feishu.secret else None
        if update.telegram:
            settings.telegram_enabled = update.telegram.enabled
            if update.telegram.botToken is not None:
                settings.telegram_token_encrypted = encrypt_secret(update.telegram.botToken) if update.telegram.botToken else None
            if update.telegram.chatId is not None:
                settings.telegram_chat_id_encrypted = encrypt_secret(update.telegram.chatId) if update.telegram.chatId else None
        if update.eventSwitches is not None:
            switches = event_switches(settings)
            switches.update(update.eventSwitches)
            settings.event_switches = json.dumps(switches)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="通知配置保存失败")
    return get_notification_config(db)


@router.post("/test-channel")
async def test_channel(body: ChannelTest, db: Session = Depends(get_db)):
    if body.channel not in {"FEISHU", "TELEGRAM"}:
        raise HTTPException(status_code=422, detail="不支持的通知通道")
    return {"success": True, "data": await NotificationService(db).test_channel(body.channel)}


@router.post("/test-event")
async def test_event(body: EventTest, request: Request, db: Session = Depends(get_db)):
    _development_frontend_only(request)
    return {"success": True, "data": await NotificationService.emit(body.event_code, body.payload, is_test=True, db=db)}


@router.get("/page-sound")
def page_sound_deliveries(after_id: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    rows = db.query(NotificationDelivery).filter(
        NotificationDelivery.id > after_id,
        NotificationDelivery.channel == "PAGE_SOUND",
        NotificationDelivery.status == "queued",
    ).order_by(NotificationDelivery.id).limit(50).all()
    return {"success": True, "data": {
        "deliveries": [{"id": row.id, "eventCode": row.event_code, "isTest": row.is_test} for row in rows],
        "pageSound": {"enabled": settings.page_sound_enabled, "soundId": settings.sound_id, "volume": settings.volume},
    }}
