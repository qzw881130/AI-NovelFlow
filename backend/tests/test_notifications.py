"""V1 notification infrastructure tests; no generation workflow is invoked."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import notifications
from app.core.database import Base, get_db
from app.models.notification import BusinessEvent, NotificationDelivery, NotificationSettings
from app.models.task import Task
from app.services import notification_channels
from app.services.notification_registry import EVENT_REGISTRY
from app.services.notification_service import NotificationService, decrypt_secret, get_or_create_settings


@pytest.fixture
def notification_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    yield db, factory
    db.close()
    engine.dispose()


@pytest.fixture
def notification_app(notification_db):
    db, _ = notification_db
    app = FastAPI()
    app.include_router(notifications.router, prefix="/api/notifications")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return app


def api_request(app, method, path, body=None, *, local=True, base_url="http://localhost", origin=None, proxy=False):
    async def run():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1" if local else "192.0.2.1", 12345))
        headers = {"Origin": base_url if origin is None else origin, "Sec-Fetch-Site": "same-origin"}
        if proxy:
            headers["X-NovelFlow-Frontend-Proxy"] = "1"
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            return await client.request(method, path, json=body, headers=headers)
    return asyncio.run(run())


def test_registry_defaults_and_config_persistence(notification_db, notification_app):
    db, factory = notification_db
    response = api_request(notification_app, "GET", "/api/notifications/config")
    data = response.json()["data"]
    assert response.status_code == 200
    # New business publishers can extend the registry without breaking existing
    # subscription semantics; the API must expose every registered key once.
    assert len(data["events"]) == len(EVENT_REGISTRY)
    assert {event["event_code"] for event in data["events"]} == set(EVENT_REGISTRY)
    assert all(event["enabled"] == EVENT_REGISTRY[event["event_code"]].enabled for event in data["events"])
    assert EVENT_REGISTRY["image.review.passed"].enabled
    assert EVENT_REGISTRY["image.review.failed"].enabled
    assert data["pageSound"] == {"enabled": True, "soundId": "chime", "volume": 0.7}
    assert not data["feishu"]["enabled"] and not data["telegram"]["enabled"]
    assert len(data["sounds"]) >= 5

    response = api_request(notification_app, "PUT", "/api/notifications/config", {
        "pageSound": {"enabled": False, "soundId": "pulse", "volume": 0.25},
        "eventSwitches": {"clip.generation.completed": False},
    })
    assert response.status_code == 200
    db.expire_all()
    with factory() as new_session:
        settings = new_session.get(NotificationSettings, "default")
        assert settings.page_sound_enabled is False
        assert settings.sound_id == "pulse"
        assert settings.volume == 0.25
        assert '"clip.generation.completed": false' in settings.event_switches
    data = api_request(notification_app, "GET", "/api/notifications/config").json()["data"]
    assert next(event for event in data["events"] if event["event_code"] == "clip.generation.completed")["enabled"] is False
    assert next(event for event in data["events"] if event["event_code"] == "shot.planning.completed")["enabled"] is True


def test_secrets_are_encrypted_and_masked(notification_db, notification_app):
    db, _ = notification_db
    response = api_request(notification_app, "PUT", "/api/notifications/config", {
        "feishu": {"enabled": True, "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/test-123", "secret": "feishu-secret"},
        "telegram": {"enabled": True, "botToken": "12345:token_TEST", "chatId": "-10012345"},
    })
    assert response.status_code == 200
    data = response.json()["data"]
    serialized = response.text
    assert data["pageSound"]["enabled"] and data["feishu"]["enabled"] and data["telegram"]["enabled"]
    for secret in ("test-123", "feishu-secret", "12345:token_TEST", "-10012345"):
        assert secret not in serialized
    assert data["feishu"]["webhookMasked"] and data["telegram"]["botTokenMasked"]
    settings = db.get(NotificationSettings, "default")
    assert decrypt_secret(settings.feishu_secret_encrypted) == "feishu-secret"
    assert decrypt_secret(settings.telegram_token_encrypted) == "12345:token_TEST"
    assert "feishu-secret" not in settings.feishu_secret_encrypted
    assert "12345:token_TEST" not in settings.telegram_token_encrypted

    # Saving empty form inputs does not overwrite previously saved credentials.
    assert api_request(notification_app, "PUT", "/api/notifications/config", {
        "feishu": {"enabled": False}, "telegram": {"enabled": False},
    }).status_code == 200
    db.refresh(settings)
    assert decrypt_secret(settings.telegram_token_encrypted) == "12345:token_TEST"


@pytest.mark.asyncio
async def test_emit_switches_and_channel_failure_isolation(notification_db, monkeypatch):
    db, _ = notification_db
    settings = get_or_create_settings(db)
    settings.feishu_enabled = True
    settings.telegram_enabled = True
    settings.feishu_webhook_encrypted = notifications.encrypt_secret("https://open.feishu.cn/open-apis/bot/v2/hook/test")
    settings.telegram_token_encrypted = notifications.encrypt_secret("123:token")
    settings.telegram_chat_id_encrypted = notifications.encrypt_secret("12345")
    db.commit()
    called = []

    async def fail_feishu(*args):
        called.append("FEISHU")
        raise RuntimeError("simulated adapter error")

    async def ok_telegram(*args):
        called.append("TELEGRAM")

    monkeypatch.setattr("app.services.notification_service.send_feishu", fail_feishu)
    monkeypatch.setattr("app.services.notification_service.send_telegram", ok_telegram)
    result = await NotificationService.emit("clip.generation.completed", {"clip_index": 2}, is_test=True, db=db)
    assert result["channels"] == {"PAGE_SOUND": "queued", "FEISHU": "failed", "TELEGRAM": "sent"}
    assert called == ["FEISHU", "TELEGRAM"]
    rows = db.query(NotificationDelivery).order_by(NotificationDelivery.id).all()
    assert [(row.channel, row.status, row.is_test) for row in rows] == [
        ("PAGE_SOUND", "queued", True), ("FEISHU", "failed", True), ("TELEGRAM", "sent", True),
    ]

    settings.event_switches = '{"clip.generation.completed": false}'
    db.commit()
    assert (await NotificationService.emit("clip.generation.completed", db=db))["status"] == "event_disabled"
    assert called == ["FEISHU", "TELEGRAM"]
    assert db.query(NotificationDelivery).count() == 3

    settings.event_switches = "{}"
    settings.page_sound_enabled = False
    settings.feishu_enabled = False
    settings.telegram_enabled = False
    db.commit()
    result = await NotificationService.emit("clip.generation.completed", db=db)
    assert result["channels"] == {"PAGE_SOUND": "disabled", "FEISHU": "disabled", "TELEGRAM": "disabled"}
    assert db.query(NotificationDelivery).count() == 3
    assert (await NotificationService.emit("not.registered", db=db))["status"] == "unknown_event"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled_channel", ["PAGE_SOUND", "FEISHU", "TELEGRAM"])
async def test_channels_can_be_enabled_independently(notification_db, monkeypatch, enabled_channel):
    db, _ = notification_db
    settings = get_or_create_settings(db)
    settings.page_sound_enabled = enabled_channel == "PAGE_SOUND"
    settings.feishu_enabled = enabled_channel == "FEISHU"
    settings.telegram_enabled = enabled_channel == "TELEGRAM"
    if settings.feishu_enabled:
        settings.feishu_webhook_encrypted = notifications.encrypt_secret("https://open.feishu.cn/open-apis/bot/v2/hook/test")
    if settings.telegram_enabled:
        settings.telegram_token_encrypted = notifications.encrypt_secret("123:token")
        settings.telegram_chat_id_encrypted = notifications.encrypt_secret("12345")
    db.commit()
    called = []

    async def feishu(*args):
        called.append("FEISHU")

    async def telegram(*args):
        called.append("TELEGRAM")

    monkeypatch.setattr("app.services.notification_service.send_feishu", feishu)
    monkeypatch.setattr("app.services.notification_service.send_telegram", telegram)
    result = await NotificationService.emit("shot.planning.completed", db=db)
    assert [channel for channel, status in result["channels"].items() if status != "disabled"] == [enabled_channel]
    assert called == ([] if enabled_channel == "PAGE_SOUND" else [enabled_channel])


def test_simulation_uses_service_and_respects_switches(notification_db, notification_app, monkeypatch):
    db, _ = notification_db
    settings = get_or_create_settings(db)
    settings.event_switches = '{"clip.generation.completed": false}'
    db.commit()
    captured = []
    original_emit = NotificationService.emit

    async def spy_emit(event_code, payload, *, is_test=False, db=None):
        captured.append((event_code, payload, is_test))
        return await original_emit(event_code, payload, is_test=is_test, db=db)

    monkeypatch.setattr(NotificationService, "emit", spy_emit)
    body = {"event_code": "clip.generation.completed", "payload": {"shot_index": 4}}
    response = api_request(notification_app, "POST", "/api/notifications/test-event", body)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "event_disabled"
    assert captured == [("clip.generation.completed", {"shot_index": 4}, True)]
    assert db.query(NotificationDelivery).count() == 0
    assert api_request(notification_app, "POST", "/api/notifications/test-event", body, local=False).status_code == 403


def test_lan_frontend_proxy_can_simulate_but_direct_and_cross_site_cannot(notification_db, notification_app, monkeypatch):
    db, _ = notification_db
    settings = get_or_create_settings(db)
    settings.feishu_enabled = True
    settings.telegram_enabled = True
    settings.feishu_webhook_encrypted = notifications.encrypt_secret("https://open.feishu.cn/open-apis/bot/v2/hook/test")
    settings.telegram_token_encrypted = notifications.encrypt_secret("123:token")
    settings.telegram_chat_id_encrypted = notifications.encrypt_secret("12345")
    db.commit()
    sent = []

    async def send_feishu(*args):
        sent.append("FEISHU")

    async def send_telegram(*args):
        sent.append("TELEGRAM")

    monkeypatch.setattr("app.services.notification_service.send_feishu", send_feishu)
    monkeypatch.setattr("app.services.notification_service.send_telegram", send_telegram)
    body = {"event_code": "clip.generation.completed", "payload": {"shot_index": 4}}
    lan = {"base_url": "http://192.168.50.3:5173", "proxy": True}

    response = api_request(notification_app, "POST", "/api/notifications/test-event", body, **lan)
    assert response.status_code == 200
    assert response.json()["data"]["channels"] == {"PAGE_SOUND": "queued", "FEISHU": "sent", "TELEGRAM": "sent"}
    assert sent == ["FEISHU", "TELEGRAM"]
    assert api_request(notification_app, "GET", "/api/notifications/page-sound?after_id=0", **lan).json()["data"]["deliveries"][0]["isTest"] is True

    settings.event_switches = '{"clip.generation.completed": false}'
    db.commit()
    response = api_request(notification_app, "POST", "/api/notifications/test-event", body, **lan)
    assert response.json()["data"]["status"] == "event_disabled"
    assert sent == ["FEISHU", "TELEGRAM"]

    settings.event_switches = "{}"
    settings.feishu_enabled = False
    db.commit()
    response = api_request(notification_app, "POST", "/api/notifications/test-event", body, **lan)
    assert response.json()["data"]["channels"] == {"PAGE_SOUND": "queued", "FEISHU": "disabled", "TELEGRAM": "sent"}
    assert sent == ["FEISHU", "TELEGRAM", "TELEGRAM"]

    assert api_request(notification_app, "POST", "/api/notifications/test-event", body,
                       base_url=lan["base_url"]).status_code == 403
    assert api_request(notification_app, "POST", "/api/notifications/test-event", body,
                       base_url=lan["base_url"], origin="http://evil.example", proxy=True).status_code == 403
    assert api_request(notification_app, "POST", "/api/notifications/test-event", body,
                       base_url=lan["base_url"], proxy=True, local=False).status_code == 403
    assert api_request(notification_app, "POST", "/api/notifications/test-event", body,
                       base_url="http://203.0.113.5:5173", proxy=True).status_code == 403
    assert api_request(notification_app, "POST", "/api/notifications/test-event", body,
                       base_url=lan["base_url"], origin="", proxy=True).status_code == 403
    monkeypatch.setattr(notifications, "get_settings", lambda: SimpleNamespace(DEBUG=False))
    assert api_request(notification_app, "POST", "/api/notifications/test-event", body, **lan).status_code == 403


def test_channel_test_obeys_switch_and_records_result(notification_db, notification_app, monkeypatch):
    db, _ = notification_db
    assert api_request(notification_app, "POST", "/api/notifications/test-channel", {"channel": "FEISHU"}).json()["data"]["status"] == "disabled"
    settings = get_or_create_settings(db)
    settings.feishu_enabled = True
    settings.feishu_webhook_encrypted = notifications.encrypt_secret("https://open.feishu.cn/open-apis/bot/v2/hook/test")
    db.commit()
    calls = []

    async def fake_send(*args):
        calls.append(args)

    monkeypatch.setattr("app.services.notification_service.send_feishu", fake_send)
    result = api_request(notification_app, "POST", "/api/notifications/test-channel", {"channel": "FEISHU"}).json()["data"]
    assert result == {"channel": "FEISHU", "status": "sent"}
    assert len(calls) == 1 and "通道测试" in calls[0][2]
    assert db.query(NotificationDelivery).filter_by(event_code="notification.channel_test", channel="FEISHU").count() == 1

    settings.telegram_enabled = True
    settings.telegram_token_encrypted = notifications.encrypt_secret("123:token")
    settings.telegram_chat_id_encrypted = notifications.encrypt_secret("12345")
    db.commit()
    monkeypatch.setattr("app.services.notification_service.send_telegram", fake_send)
    result = api_request(notification_app, "POST", "/api/notifications/test-channel", {"channel": "TELEGRAM"}).json()["data"]
    assert result == {"channel": "TELEGRAM", "status": "sent"}
    assert len(calls) == 2 and "通道测试" in calls[1][2]


@pytest.mark.asyncio
async def test_adapters_send_expected_requests_without_external_network(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "api.telegram.org":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={"code": 0})

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(notification_channels.httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport))
    await notification_channels.send_feishu("https://open.feishu.cn/open-apis/bot/v2/hook/test", "secret", "飞书测试")
    await notification_channels.send_telegram("123:token", "-100123", "Telegram 测试")
    assert len(requests) == 2
    assert b'"sign"' in requests[0].content and b'"timestamp"' in requests[0].content
    assert json.loads(requests[1].content)["chat_id"] == "-100123"
    assert requests[1].url.path == "/bot123:token/sendMessage"
    assert not notification_channels.validate_feishu_webhook("http://127.0.0.1/open-apis/bot/v2/hook/unsafe")


def test_development_endpoint_formats_five_events_without_business_tasks(notification_db, notification_app, monkeypatch):
    db, _ = notification_db
    settings = get_or_create_settings(db)
    settings.feishu_enabled = settings.telegram_enabled = True
    db.commit()
    sent = []

    async def fake_send(*args):
        sent.append(args[-1])

    monkeypatch.setattr("app.services.notification_service.send_feishu", fake_send)
    monkeypatch.setattr("app.services.notification_service.send_telegram", fake_send)
    monkeypatch.setattr("app.services.notification_service.decrypt_secret", lambda _: "mock")
    cases = [
        ("shot.planning.completed", {"shot_index": 7}, "Shot 7 规划完成"),
        ("clip.prompt.build.failed", {"shot_index": 7, "clip_index": 1,
                                      "error_code": "DIALOGUE_DUPLICATED_IN_PROMPT"}, "Shot 7 · C1"),
        ("clip.generation.failed", {"shot_index": 7, "clip_index": 1,
                                    "error_code": "DIALOGUE_DUPLICATED_IN_PROMPT"}, "Shot 7 · C1 生成失败"),
        ("clip.prompt.optimize.failed", {"shot_index": 7, "clip_index": 1,
                                         "error_code": "PREFLIGHT_FAIL"}, "Shot 7 · C1"),
        ("preflight.repair.failed", {"shot_index": 7, "clip_index": 1,
                                    "error_code": "PREFLIGHT_FAIL"}, "Shot 7 · C1"),
    ]
    for code, payload, expected in cases:
        response = api_request(notification_app, "POST", "/api/notifications/test-event",
                               {"event_code": code, "payload": payload})
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "processed"
        assert sent[-1] == sent[-2]
        assert expected in sent[-1]
        assert "开发模拟事件" in sent[-1]
        assert "事件：" not in sent[-1] and "数据：" not in sent[-1]
        assert "DIALOGUE_DUPLICATED_IN_PROMPT" not in sent[-1]
        assert "PREFLIGHT_FAIL" not in sent[-1]
    assert len(sent) == 10
    assert db.query(BusinessEvent).count() == 5
    assert db.query(Task).count() == 0


def test_development_endpoint_sequential_failure_chain_sends_one_final_message(notification_db, notification_app, monkeypatch):
    db, _ = notification_db
    settings = get_or_create_settings(db)
    settings.feishu_enabled = settings.telegram_enabled = True
    db.commit()
    sent = []

    async def fake_send(*args):
        sent.append(args[-1])

    monkeypatch.setattr("app.services.notification_service.send_feishu", fake_send)
    monkeypatch.setattr("app.services.notification_service.send_telegram", fake_send)
    monkeypatch.setattr("app.services.notification_service.decrypt_secret", lambda _: "mock")
    payload = {"shot_index": 7, "clip_index": 1, "task_id": "simulated-c1-failure",
               "error_code": "DIALOGUE_DUPLICATED_IN_PROMPT"}
    first = api_request(notification_app, "POST", "/api/notifications/test-event",
                        {"event_code": "clip.prompt.build.failed", "payload": payload}).json()["data"]
    assert first["status"] == "pending"
    assert first["channels"] == {"PAGE_SOUND": "queued", "FEISHU": "deferred", "TELEGRAM": "deferred"}
    assert not sent
    second = api_request(notification_app, "POST", "/api/notifications/test-event",
                         {"event_code": "clip.generation.failed", "payload": payload}).json()["data"]
    assert second["status"] == "processed"
    prompt = db.query(BusinessEvent).filter_by(event_type="clip.prompt.build.failed").one()
    asyncio.run(NotificationService.dispatch_event(db, prompt.id))
    assert len(sent) == 2 and sent[0] == sent[1]
    assert sent[0].startswith("❌ NovelFlow｜Shot 7 · C1 生成失败")
    assert db.query(Task).count() == 0
