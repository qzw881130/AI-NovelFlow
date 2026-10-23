"""Outbound adapters. Exceptions are deliberately handled by NotificationService."""
import base64
import hashlib
import hmac
import time
from urllib.parse import urlsplit

import httpx


def validate_feishu_webhook(webhook: str) -> bool:
    try:
        url = urlsplit(webhook)
        return (
            url.scheme == "https"
            and url.hostname in {"open.feishu.cn", "open.larksuite.com"}
            and url.path.startswith("/open-apis/bot/v2/hook/")
            and bool(url.path.removeprefix("/open-apis/bot/v2/hook/"))
            and url.port in {None, 443}
            and not url.username
            and not url.password
        )
    except ValueError:
        return False


async def send_feishu(webhook: str, secret: str, message: str) -> None:
    body = {"msg_type": "text", "content": {"text": message}}
    if secret:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{secret}"
        signature = base64.b64encode(hmac.new(string_to_sign.encode(), b"", hashlib.sha256).digest()).decode()
        body.update({"timestamp": timestamp, "sign": signature})
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
        response = await client.post(webhook, json=body)
        response.raise_for_status()
        data = response.json()
        if data.get("code", data.get("StatusCode")) != 0:
            raise RuntimeError("飞书机器人拒绝了消息")


async def send_telegram(token: str, chat_id: str, message: str) -> None:
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
        )
        response.raise_for_status()
        if response.json().get("ok") is not True:
            raise RuntimeError("Telegram Bot API 拒绝了消息")
