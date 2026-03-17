import hashlib
import hmac
import base64
import json

from app.core.config import Settings, get_settings
from app.main import app


def _daily_signature(payload: bytes, secret_base64: str, timestamp: str) -> str:
    secret_bytes = base64.b64decode(secret_base64)
    signed_payload = timestamp.encode() + b"." + payload
    return base64.b64encode(
        hmac.new(secret_bytes, signed_payload, hashlib.sha256).digest()
    ).decode()


async def test_daily_webhook_accepts_unsigned_test_probe(client):
    payload = b'{"test":"test"}'
    resp = await client.post("/api/v1/video/webhooks/daily", content=payload)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_daily_webhook_rejects_invalid_signature(client):
    payload = b'{"event":"participant.joined"}'
    secret = base64.b64encode(b"test-webhook-secret").decode()

    app.dependency_overrides[get_settings] = lambda: Settings(
        daily_webhook_secret=secret
    )
    try:
        resp = await client.post(
            "/api/v1/video/webhooks/daily",
            content=payload,
            headers={
                "x-webhook-signature": "invalid-signature",
                "x-webhook-timestamp": "1710000000",
            },
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert resp.status_code == 401


async def test_daily_webhook_accepts_valid_signature(client):
    secret = base64.b64encode(b"test-webhook-secret").decode()
    timestamp = "1710000000"
    payload = json.dumps(
        {"event": "participant.joined"}, separators=(",", ":")
    ).encode()
    signature = _daily_signature(payload, secret, timestamp)

    app.dependency_overrides[get_settings] = lambda: Settings(
        daily_webhook_secret=secret
    )
    try:
        resp = await client.post(
            "/api/v1/video/webhooks/daily",
            content=payload,
            headers={
                "x-webhook-signature": signature,
                "x-webhook-timestamp": timestamp,
            },
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
