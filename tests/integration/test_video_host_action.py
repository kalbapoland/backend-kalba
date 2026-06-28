"""Tests for the host-only `remove_participant` action on the host-action endpoint.

The host (trainer) can eject a participant from the live call. Enforcement of the
ejection itself happens on the host's Daily owner client; the backend only
authorizes (host-only) and audits the request.
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.core.config import Settings, get_settings
from app.main import app
from app.models.video import WorkshopParticipant
from app.models.workshop import Workshop
from app.services.daily import DailyService, get_daily_service


class _FakeDaily(DailyService):
    """Daily wrapper that never hits the network."""

    def __init__(self):
        pass

    async def create_room(self, name, *, max_participants, start_time, duration_minutes):
        return {"name": name, "url": f"https://test.daily.co/{name}"}

    async def create_meeting_token(self, room_name, **kwargs):
        return "fake-token"

    async def send_app_message(self, room_name, data, *, recipient="*"):
        return None


def _use_settings(**overrides):
    app.dependency_overrides[get_settings] = lambda: Settings(**overrides)


def _use_fake_daily():
    app.dependency_overrides[get_daily_service] = lambda: _FakeDaily()


def _clear_overrides():
    app.dependency_overrides.pop(get_settings, None)
    app.dependency_overrides.pop(get_daily_service, None)


async def _make_workshop(db_session, trainer, group, *, duration=60) -> Workshop:
    ws = Workshop(
        trainer_id=trainer.id,
        group_id=group.id,
        title="Host Action Test",
        start_time=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5),
        duration_minutes=duration,
        max_participants=10,
    )
    db_session.add(ws)
    await db_session.commit()
    await db_session.refresh(ws)
    return ws


async def test_host_can_remove_participant(
    client, db_session, trainer, regular_user, group, trainer_token
):
    ws = await _make_workshop(db_session, trainer, group)
    resp = await client.post(
        f"/api/v1/video/workshops/{ws.id}/host-action",
        headers={"Authorization": f"Bearer {trainer_token}"},
        json={"action": "remove_participant", "target_user_id": str(regular_user.id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["action"] == "remove_participant"
    assert body["broadcast_sent"] is False


async def test_non_host_cannot_remove_participant(
    client, db_session, trainer, regular_user, group, user_token
):
    ws = await _make_workshop(db_session, trainer, group)
    resp = await client.post(
        f"/api/v1/video/workshops/{ws.id}/host-action",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"action": "remove_participant", "target_user_id": str(trainer.id)},
    )
    assert resp.status_code == 403, resp.text


async def test_remove_participant_requires_target(
    client, db_session, trainer, group, trainer_token
):
    ws = await _make_workshop(db_session, trainer, group)
    resp = await client.post(
        f"/api/v1/video/workshops/{ws.id}/host-action",
        headers={"Authorization": f"Bearer {trainer_token}"},
        json={"action": "remove_participant"},
    )
    assert resp.status_code == 422, resp.text


async def test_host_cannot_remove_themselves(
    client, db_session, trainer, group, trainer_token
):
    ws = await _make_workshop(db_session, trainer, group)
    resp = await client.post(
        f"/api/v1/video/workshops/{ws.id}/host-action",
        headers={"Authorization": f"Bearer {trainer_token}"},
        json={"action": "remove_participant", "target_user_id": str(trainer.id)},
    )
    assert resp.status_code == 400, resp.text


async def _kick(client, ws, trainer_token, target):
    resp = await client.post(
        f"/api/v1/video/workshops/{ws.id}/host-action",
        headers={"Authorization": f"Bearer {trainer_token}"},
        json={"action": "remove_participant", "target_user_id": str(target.id)},
    )
    assert resp.status_code == 200, resp.text


async def test_kicked_participant_cannot_immediately_rejoin(
    client, db_session, trainer, regular_user, group, trainer_token, user_token
):
    ws = await _make_workshop(db_session, trainer, group)
    await _kick(client, ws, trainer_token, regular_user)

    _use_settings()  # default 60s cooldown, big budget
    _use_fake_daily()
    try:
        resp = await client.post(
            f"/api/v1/video/workshops/{ws.id}/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
    finally:
        _clear_overrides()

    assert resp.status_code == 403, resp.text
    assert "removed" in resp.json()["detail"].lower()
    assert resp.headers.get("Retry-After") is not None


async def test_kicked_participant_can_rejoin_after_cooldown(
    client, db_session, trainer, regular_user, group, trainer_token, user_token
):
    ws = await _make_workshop(db_session, trainer, group)
    await _kick(client, ws, trainer_token, regular_user)

    # Move the kick well past the cooldown window.
    row = (
        await db_session.exec(
            select(WorkshopParticipant).where(
                WorkshopParticipant.workshop_id == ws.id,
                WorkshopParticipant.user_id == regular_user.id,
            )
        )
    ).first()
    row.kicked_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=120)
    db_session.add(row)
    await db_session.commit()

    _use_settings()
    _use_fake_daily()
    try:
        resp = await client.post(
            f"/api/v1/video/workshops/{ws.id}/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
    finally:
        _clear_overrides()

    assert resp.status_code == 200, resp.text


async def test_cooldown_disabled_allows_immediate_rejoin(
    client, db_session, trainer, regular_user, group, trainer_token, user_token
):
    ws = await _make_workshop(db_session, trainer, group)
    await _kick(client, ws, trainer_token, regular_user)

    _use_settings(workshop_kick_cooldown_seconds=0)
    _use_fake_daily()
    try:
        resp = await client.post(
            f"/api/v1/video/workshops/{ws.id}/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
    finally:
        _clear_overrides()

    assert resp.status_code == 200, resp.text
