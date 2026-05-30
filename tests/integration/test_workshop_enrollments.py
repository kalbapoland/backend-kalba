from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.models.workshop import Workshop, WorkshopEnrollment


@pytest.fixture
def workshop_payload(group):
    return {
        "title": "Morning Meditation",
        "description": "A relaxing session",
        "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "duration_minutes": 60,
        "price": "10.00",
        "max_participants": 2,
        "group_id": str(group.id),
    }


async def _create_workshop(client, trainer_token, payload):
    resp = await client.post(
        "/api/v1/workshops/",
        json=payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# --- POST /workshops/{id}/enroll ---


async def test_enroll_workshop_happy_path(
    client, trainer_token, user_token, workshop_payload, group, regular_user, subscribe
):
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)
    await subscribe(group, regular_user)

    resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_enrolled"] is True
    assert body["is_owner"] is False
    assert body["enrolled_count"] == 1


async def test_enroll_is_idempotent(
    client, trainer_token, user_token, workshop_payload, group, regular_user, subscribe
):
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)
    await subscribe(group, regular_user)

    headers = {"Authorization": f"Bearer {user_token}"}
    first = await client.post(f"/api/v1/workshops/{workshop_id}/enroll", headers=headers)
    second = await client.post(f"/api/v1/workshops/{workshop_id}/enroll", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["enrolled_count"] == 1


async def test_trainer_cannot_enroll_in_own_workshop(
    client, trainer_token, workshop_payload
):
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)

    resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 400


async def test_enroll_nonexistent_workshop_returns_404(client, user_token):
    resp = await client.post(
        "/api/v1/workshops/00000000-0000-0000-0000-000000000000/enroll",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 404


async def test_enroll_unauthenticated_returns_401(client, trainer_token, workshop_payload):
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)
    resp = await client.post(f"/api/v1/workshops/{workshop_id}/enroll")
    assert resp.status_code == 401


async def test_enroll_full_workshop_returns_409(
    client, trainer_token, user_token, workshop_payload, group, regular_user,
    subscribe, db_session
):
    workshop_payload["max_participants"] = 1
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)
    await subscribe(group, regular_user)

    # First enrollment by regular user
    first = await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert first.status_code == 200

    # Create a second user, subscribe them, and try to enroll
    other = User(
        email="other@test.com",
        full_name="Other",
        google_id="google-other-789",
        role=UserRole.USER,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    await subscribe(group, other)
    other_token = create_access_token(other.id)

    resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 409
    assert "full" in resp.json()["detail"].lower()


async def test_enroll_requires_group_membership(
    client, trainer_token, user_token, workshop_payload
):
    """A user who has not joined the group cannot enroll in its workshops."""
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)

    resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


async def test_enroll_started_workshop_is_rejected(
    client, trainer_token, user_token, workshop_payload, group, regular_user,
    subscribe, db_session
):
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)
    await subscribe(group, regular_user)

    # Force the workshop into the past (bypasses the create-time future check)
    workshop = await db_session.get(Workshop, workshop_id)
    workshop.start_time = (datetime.now(UTC) - timedelta(minutes=5)).replace(tzinfo=None)
    db_session.add(workshop)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 400


async def test_enroll_soft_deleted_workshop_returns_404(
    client, trainer_token, user_token, workshop_payload, db_session
):
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)

    workshop = await db_session.get(Workshop, workshop_id)
    workshop.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    db_session.add(workshop)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 404


# --- DELETE /workshops/{id}/enroll ---


async def test_unenroll_happy_path(
    client, trainer_token, user_token, workshop_payload, group, regular_user, subscribe
):
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)
    await subscribe(group, regular_user)

    headers = {"Authorization": f"Bearer {user_token}"}
    await client.post(f"/api/v1/workshops/{workshop_id}/enroll", headers=headers)
    resp = await client.delete(f"/api/v1/workshops/{workshop_id}/enroll", headers=headers)
    assert resp.status_code == 204

    # Confirm flag flipped
    detail = await client.get(f"/api/v1/workshops/{workshop_id}", headers=headers)
    assert detail.json()["is_enrolled"] is False
    assert detail.json()["enrolled_count"] == 0


async def test_unenroll_is_idempotent(client, trainer_token, user_token, workshop_payload):
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)
    headers = {"Authorization": f"Bearer {user_token}"}

    # Never enrolled — still 204
    resp = await client.delete(f"/api/v1/workshops/{workshop_id}/enroll", headers=headers)
    assert resp.status_code == 204


# --- GET /workshops/mine ---


async def test_mine_returns_owned_and_enrolled(
    client, trainer_token, user_token, workshop_payload, group, regular_user,
    subscribe, db_session
):
    # Trainer creates A and B; user enrolls in A
    workshop_a = await _create_workshop(
        client, trainer_token, {**workshop_payload, "title": "A"}
    )
    workshop_b = await _create_workshop(
        client,
        trainer_token,
        {
            **workshop_payload,
            "title": "B",
            "start_time": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
    )
    await subscribe(group, regular_user)
    user_headers = {"Authorization": f"Bearer {user_token}"}
    await client.post(f"/api/v1/workshops/{workshop_a}/enroll", headers=user_headers)

    # User's /mine — sees only A (enrolled)
    resp = await client.get("/api/v1/workshops/mine", headers=user_headers)
    assert resp.status_code == 200
    titles = {w["title"] for w in resp.json()}
    assert titles == {"A"}

    # Trainer's /mine — sees A and B (owned), neither enrolled
    trainer_headers = {"Authorization": f"Bearer {trainer_token}"}
    resp = await client.get("/api/v1/workshops/mine", headers=trainer_headers)
    titles = {w["title"] for w in resp.json()}
    assert titles == {"A", "B"}
    for w in resp.json():
        assert w["is_owner"] is True
        assert w["is_enrolled"] is False


async def test_mine_role_filter(
    client, trainer_token, user_token, workshop_payload, group, regular_user, subscribe
):
    workshop_a = await _create_workshop(
        client, trainer_token, {**workshop_payload, "title": "A"}
    )
    await subscribe(group, regular_user)
    user_headers = {"Authorization": f"Bearer {user_token}"}
    await client.post(f"/api/v1/workshops/{workshop_a}/enroll", headers=user_headers)

    # role=trainer for the regular user → empty
    resp = await client.get("/api/v1/workshops/mine?role=trainer", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json() == []

    # role=enrolled → A
    resp = await client.get("/api/v1/workshops/mine?role=enrolled", headers=user_headers)
    assert {w["title"] for w in resp.json()} == {"A"}


async def test_mine_date_range_filter(
    client, trainer_token, workshop_payload
):
    # Two workshops, one tomorrow, one in 10 days
    near = await _create_workshop(
        client, trainer_token, {**workshop_payload, "title": "Near"}
    )
    far = await _create_workshop(
        client,
        trainer_token,
        {
            **workshop_payload,
            "title": "Far",
            "start_time": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
        },
    )

    headers = {"Authorization": f"Bearer {trainer_token}"}
    # Use Z suffix so the `+` in `+00:00` is not interpreted as URL-space.
    from_ = (
        (datetime.now(UTC) + timedelta(days=5))
        .replace(tzinfo=None)
        .isoformat()
        + "Z"
    )
    resp = await client.get(
        f"/api/v1/workshops/mine?from={from_}", headers=headers
    )
    assert resp.status_code == 200
    titles = {w["title"] for w in resp.json()}
    assert titles == {"Far"}


async def test_mine_excludes_soft_deleted(
    client, trainer_token, workshop_payload, db_session
):
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)
    workshop = await db_session.get(Workshop, workshop_id)
    workshop.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    db_session.add(workshop)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/workshops/mine",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_mine_requires_auth(client):
    resp = await client.get("/api/v1/workshops/mine")
    assert resp.status_code == 401


# --- WorkshopRead caller-context fields on other endpoints ---


async def test_detail_returns_is_enrolled_when_authenticated(
    client, trainer_token, user_token, workshop_payload, group, regular_user, subscribe
):
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)
    await subscribe(group, regular_user)
    headers = {"Authorization": f"Bearer {user_token}"}

    before = await client.get(f"/api/v1/workshops/{workshop_id}", headers=headers)
    assert before.json()["is_enrolled"] is False

    await client.post(f"/api/v1/workshops/{workshop_id}/enroll", headers=headers)

    after = await client.get(f"/api/v1/workshops/{workshop_id}", headers=headers)
    assert after.json()["is_enrolled"] is True
    assert after.json()["enrolled_count"] == 1


async def test_detail_hidden_from_non_member(
    client, trainer_token, user_token, workshop_payload
):
    """A non-member can't even see a workshop in a group they haven't joined."""
    workshop_id = await _create_workshop(client, trainer_token, workshop_payload)

    # Anonymous and non-member callers both get 404 (existence is hidden).
    anon = await client.get(f"/api/v1/workshops/{workshop_id}")
    assert anon.status_code == 404

    non_member = await client.get(
        f"/api/v1/workshops/{workshop_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert non_member.status_code == 404


async def test_create_returns_is_owner_true(
    client, trainer_token, workshop_payload
):
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["is_owner"] is True
