"""Tests for the Daily.co participant-minute budget guard.

The guard guarantees we never cross the free tier into paid usage: every join
reserves its worst-case minutes before a token is issued, and joins are refused
once the rolling-window cap would be exceeded.
"""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.core.config import Settings, get_settings
from app.main import app
from app.models.workshop import Workshop
from app.models.video import VideoUsageSession
from app.services.daily import DailyService, get_daily_service


class _FakeDaily(DailyService):
    """Daily wrapper that never hits the network (keeps real signature verify)."""

    def __init__(self):
        pass

    async def create_room(self, name, *, max_participants, start_time, duration_minutes):
        return {"name": name, "url": f"https://test.daily.co/{name}"}

    async def create_meeting_token(self, room_name, **kwargs):
        return "fake-token"

    async def send_app_message(self, room_name, data, *, recipient="*"):
        return None


def _daily_signature(payload: bytes, secret_base64: str, timestamp: str) -> str:
    secret_bytes = base64.b64decode(secret_base64)
    signed = timestamp.encode() + b"." + payload
    return base64.b64encode(
        hmac.new(secret_bytes, signed, hashlib.sha256).digest()
    ).decode()


async def _make_workshop(db_session, trainer, group, *, duration=60) -> Workshop:
    ws = Workshop(
        trainer_id=trainer.id,
        group_id=group.id,
        title="Budget Test",
        start_time=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5),
        duration_minutes=duration,
        max_participants=10,
    )
    db_session.add(ws)
    await db_session.commit()
    await db_session.refresh(ws)
    return ws


def _use_settings(**overrides):
    app.dependency_overrides[get_settings] = lambda: Settings(**overrides)


def _use_fake_daily():
    app.dependency_overrides[get_daily_service] = lambda: _FakeDaily()


def _clear_overrides():
    app.dependency_overrides.pop(get_settings, None)
    app.dependency_overrides.pop(get_daily_service, None)


async def test_join_creates_a_reservation(client, db_session, trainer, group, trainer_token):
    ws = await _make_workshop(db_session, trainer, group)
    _use_settings()  # default: big budget
    _use_fake_daily()
    try:
        resp = await client.post(
            f"/api/v1/video/workshops/{ws.id}/join",
            headers={"Authorization": f"Bearer {trainer_token}"},
        )
    finally:
        _clear_overrides()

    assert resp.status_code == 200
    rows = (
        await db_session.exec(
            select(VideoUsageSession).where(VideoUsageSession.workshop_id == ws.id)
        )
    ).all()
    assert len(rows) == 1
    # 60-min workshop + 10 grace, host joins ~5 min early -> ~75 worst-case min.
    assert rows[0].reserved_minutes >= 60
    assert rows[0].settled is False


async def test_join_blocked_when_budget_exhausted(client, db_session, trainer, group, trainer_token):
    ws = await _make_workshop(db_session, trainer, group)
    # Tiny cap: free=10, ratio=1.0 -> cap 10; a 60-min workshop needs ~75.
    _use_settings(daily_free_minutes_per_month=10, daily_usage_safety_ratio=1.0)
    _use_fake_daily()
    try:
        resp = await client.post(
            f"/api/v1/video/workshops/{ws.id}/join",
            headers={"Authorization": f"Bearer {trainer_token}"},
        )
    finally:
        _clear_overrides()

    assert resp.status_code == 503
    # No reservation is left behind when blocked.
    rows = (
        await db_session.exec(
            select(VideoUsageSession).where(VideoUsageSession.workshop_id == ws.id)
        )
    ).all()
    assert rows == []


async def test_enforcement_kill_switch_allows_over_budget(client, db_session, trainer, group, trainer_token):
    ws = await _make_workshop(db_session, trainer, group)
    _use_settings(
        daily_free_minutes_per_month=10,
        daily_usage_safety_ratio=1.0,
        daily_budget_enforcement_enabled=False,
    )
    _use_fake_daily()
    try:
        resp = await client.post(
            f"/api/v1/video/workshops/{ws.id}/join",
            headers={"Authorization": f"Bearer {trainer_token}"},
        )
    finally:
        _clear_overrides()

    assert resp.status_code == 200


async def test_rejoin_reuses_reservation(client, db_session, trainer, group, trainer_token):
    ws = await _make_workshop(db_session, trainer, group)
    _use_settings()
    _use_fake_daily()
    try:
        for _ in range(3):
            resp = await client.post(
                f"/api/v1/video/workshops/{ws.id}/join",
                headers={"Authorization": f"Bearer {trainer_token}"},
            )
            assert resp.status_code == 200
    finally:
        _clear_overrides()

    rows = (
        await db_session.exec(
            select(VideoUsageSession).where(VideoUsageSession.workshop_id == ws.id)
        )
    ).all()
    assert len(rows) == 1  # reconnects refresh, never stack


async def test_webhook_participant_left_settles_reservation(
    client, db_session, trainer, group, trainer_token
):
    ws = await _make_workshop(db_session, trainer, group)
    secret = base64.b64encode(b"budget-test-secret").decode()
    _use_settings(daily_webhook_secret=secret)
    _use_fake_daily()
    try:
        join = await client.post(
            f"/api/v1/video/workshops/{ws.id}/join",
            headers={"Authorization": f"Bearer {trainer_token}"},
        )
        assert join.status_code == 200

        payload = json.dumps(
            {
                "event": "participant.left",
                "payload": {
                    "room": f"kalba-{ws.id}",
                    "user_id": str(trainer.id),
                    "duration": 120,  # 2 minutes actually spent
                },
            },
            separators=(",", ":"),
        ).encode()
        timestamp = "1710000000"
        sig = _daily_signature(payload, secret, timestamp)

        resp = await client.post(
            "/api/v1/video/webhooks/daily",
            content=payload,
            headers={
                "x-webhook-signature": sig,
                "x-webhook-timestamp": timestamp,
            },
        )
        assert resp.status_code == 200
    finally:
        _clear_overrides()

    db_session.expunge_all()
    row = (
        await db_session.exec(
            select(VideoUsageSession).where(VideoUsageSession.workshop_id == ws.id)
        )
    ).one()
    assert row.settled is True
    assert row.actual_minutes == 2  # ceil(120s / 60)


async def test_budget_endpoint_reports_status(client, db_session, trainer, group, trainer_token):
    ws = await _make_workshop(db_session, trainer, group)
    _use_settings()
    _use_fake_daily()
    try:
        await client.post(
            f"/api/v1/video/workshops/{ws.id}/join",
            headers={"Authorization": f"Bearer {trainer_token}"},
        )
        resp = await client.get(
            "/api/v1/video/budget",
            headers={"Authorization": f"Bearer {trainer_token}"},
        )
    finally:
        _clear_overrides()

    assert resp.status_code == 200
    body = resp.json()
    assert body["cap_minutes"] == 8000  # 10000 * 0.8
    assert body["used_minutes"] >= 60
    assert body["remaining_minutes"] == body["cap_minutes"] - body["used_minutes"]
    assert body["enforced"] is True
