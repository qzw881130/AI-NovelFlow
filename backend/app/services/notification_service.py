"""Existing channel dispatch, backed by an independent durable business event ledger."""
import asyncio
import json
import logging
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import get_encryption_key
from app.models.notification import BusinessEvent, NotificationDelivery, NotificationSettings
from app.services.notification_channels import send_feishu, send_telegram
from app.services.notification_dedupe import INTERMEDIATE_FAILURES, failure_delivery_decision
from app.services.notification_format import format_notification, resolve_business_context
from app.services.notification_registry import EVENT_REGISTRY

logger = logging.getLogger(__name__)

SOUNDS = {
    "chime": "清脆提示",
    "bell": "轻铃",
    "success": "完成音",
    "soft": "柔和提示",
    "pulse": "双音提示",
}


def encrypt_secret(value: str) -> str:
    # Use strict encryption: the legacy helper can silently fall back to plaintext.
    return Fernet(get_encryption_key()).encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str:
    return Fernet(get_encryption_key()).decrypt(value.encode()).decode() if value else ""


def get_or_create_settings(db: Session) -> NotificationSettings:
    settings = db.get(NotificationSettings, "default")
    if settings is None:
        settings = NotificationSettings(id="default")
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def event_switches(settings: NotificationSettings) -> dict[str, bool]:
    try:
        switches = json.loads(settings.event_switches or "{}")
        return switches if isinstance(switches, dict) else {}
    except (TypeError, ValueError):
        return {}


def mask_secret(value: str | None) -> str:
    return "••••••（已配置）" if value else ""


class NotificationService:
    def __init__(self, db: Session | None = None):
        self.db = db

    @staticmethod
    async def emit(event_code: str, payload: dict[str, Any] | None = None, *, is_test: bool = False,
                   db: Session | None = None, dedupe_key: str | None = None) -> dict:
        """Compatibility API for simulation/direct publishers: persist BEFORE dispatch."""
        if event_code not in EVENT_REGISTRY:
            return {"event_code": event_code, "status": "unknown_event", "channels": {}}
        owns_db = db is None
        try:
            from app.services.business_events import record_event
            db = db or SessionLocal()
            row = record_event(db, event_code, payload, is_test=is_test, dedupe_key=dedupe_key)
            return await NotificationService.dispatch_event(db, row.id)
        except Exception:
            logger.exception("Notification dispatch failed for %s", event_code)
            return {"event_code": event_code, "status": "failed", "channels": {}}
        finally:
            if owns_db and db is not None:
                db.close()

    @staticmethod
    async def dispatch_event(db, event_id):
        row = db.get(BusinessEvent, event_id)
        if not row:
            return {"status": "not_found", "channels": {}}
        result = {"event_id": row.id, "event_code": row.event_type, "channels": {}}
        claimed = db.query(BusinessEvent).filter_by(id=event_id, notification_status="pending").update(
            {"notification_status": "sending"}, synchronize_session=False)
        db.commit()
        db.refresh(row)
        if not claimed:
            return {**result, "status": row.notification_status}
        try:
            settings = get_or_create_settings(db)
            if not event_switches(settings).get(row.event_type, EVENT_REGISTRY[row.event_type].enabled):
                result["status"] = "event_disabled"
            else:
                try:
                    decision = failure_delivery_decision(
                        db, row,
                        final_subscribed=event_switches(settings).get(
                            "clip.generation.failed", EVENT_REGISTRY["clip.generation.failed"].enabled),
                        external_enabled=settings.feishu_enabled or settings.telegram_enabled,
                    )
                except Exception:
                    db.rollback()
                    logger.warning("Notification chain unavailable for %s", event_id)
                    decision = "send"
                message = None
                if decision == "send" and (settings.feishu_enabled or settings.telegram_enabled):
                    try:
                        context = resolve_business_context(db, row)
                    except Exception:
                        db.rollback()
                        logger.warning("Notification context unavailable for %s", event_id)
                        context = {}
                    message = format_notification(row, context)
                for channel, enabled in (("PAGE_SOUND", settings.page_sound_enabled),
                                         ("FEISHU", settings.feishu_enabled),
                                         ("TELEGRAM", settings.telegram_enabled)):
                    if not enabled:
                        result["channels"][channel] = "disabled"
                        continue
                    if channel == "PAGE_SOUND" and row.event_type in INTERMEDIATE_FAILURES:
                        existing_sound = db.query(NotificationDelivery.id).filter_by(
                            event_code=row.event_type, channel="PAGE_SOUND",
                            detail=json.dumps({"event_id": row.id}),
                        ).first()
                        if existing_sound:
                            result["channels"][channel] = "queued"
                            continue
                    if channel != "PAGE_SOUND" and decision in {"hold", "suppress"}:
                        status = "deferred" if decision == "hold" else "suppressed_duplicate"
                        result["channels"][channel] = status
                        if decision == "suppress":
                            NotificationService._record(db, row.event_type, channel, status, row.is_test, row.id)
                        continue
                    try:
                        if channel == "PAGE_SOUND":
                            status = "queued"
                        elif channel == "FEISHU":
                            await send_feishu(decrypt_secret(settings.feishu_webhook_encrypted),
                                              decrypt_secret(settings.feishu_secret_encrypted), message)
                            status = "sent"
                        else:
                            await send_telegram(decrypt_secret(settings.telegram_token_encrypted),
                                                decrypt_secret(settings.telegram_chat_id_encrypted), message)
                            status = "sent"
                    except Exception as exc:
                        logger.warning("Notification %s failed for %s (%s)", channel, row.id, type(exc).__name__)
                        status = "failed"
                    result["channels"][channel] = status
                    NotificationService._record(db, row.event_type, channel, status, row.is_test, row.id)
                result["status"] = "pending" if decision == "hold" else "processed"
        except Exception:
            db.rollback()
            logger.exception("Event retained; notification delivery failed: %s", event_id)
            result["status"] = "failed"
        row.notification_status = result["status"]
        row.notification_result = json.dumps(result, ensure_ascii=False)
        db.commit()
        return result

    async def test_channel(self, channel: str) -> dict:
        """Direct channel connectivity test; simulated events use emit instead."""
        db = self.db
        try:
            db = db or SessionLocal()
            settings = get_or_create_settings(db)
            if channel == "FEISHU":
                enabled = settings.feishu_enabled
                send = lambda: send_feishu(
                    decrypt_secret(settings.feishu_webhook_encrypted),
                    decrypt_secret(settings.feishu_secret_encrypted),
                    "[NovelFlow 通道测试] 此消息仅验证飞书通知配置。",
                )
            elif channel == "TELEGRAM":
                enabled = settings.telegram_enabled
                send = lambda: send_telegram(
                    decrypt_secret(settings.telegram_token_encrypted),
                    decrypt_secret(settings.telegram_chat_id_encrypted),
                    "[NovelFlow 通道测试] 此消息仅验证 Telegram 通知配置。",
                )
            else:
                return {"channel": channel, "status": "unknown_channel"}
            if not enabled:
                return {"channel": channel, "status": "disabled"}
            try:
                await send()
                status = "sent"
            except Exception as exc:
                logger.warning("Notification channel test failed: %s (%s)", channel, type(exc).__name__)
                status = "failed"
            self._record(db, "notification.channel_test", channel, status, True)
            return {"channel": channel, "status": status}
        except Exception:
            logger.exception("Notification channel test could not run: %s", channel)
            return {"channel": channel, "status": "failed"}
        finally:
            if self.db is None and db is not None:
                try:
                    db.close()
                except Exception:
                    logger.warning("Could not close notification database session")

    @staticmethod
    def _record(db: Session, event_code: str, channel: str, status: str, is_test: bool, event_id: str | None = None) -> None:
        try:
            db.add(NotificationDelivery(
                event_code=event_code, channel=channel, status=status, is_test=is_test,
                detail=json.dumps({"event_id": event_id}) if event_id else None,
            ))
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not save notification delivery result")


async def notification_dispatch_loop():
    # An interrupted external send has unknown delivery outcome. Preserve it for
    # inspection instead of silently sending it a second time after a restart.
    with SessionLocal() as db:
        db.query(BusinessEvent).filter_by(notification_status="sending").update(
            {"notification_status": "interrupted"}, synchronize_session=False)
        db.commit()
    while True:
        try:
            with SessionLocal() as db:
                ids = [item[0] for item in db.query(BusinessEvent.id).filter_by(
                    notification_status="pending").order_by(BusinessEvent.recorded_at).limit(20).all()]
                for event_id in ids:
                    await NotificationService.dispatch_event(db, event_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Event notification worker failed; generation is unaffected")
        await asyncio.sleep(2)
