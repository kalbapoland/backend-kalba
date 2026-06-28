from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.models.workshop import Workshop


@pytest.fixture
def workshop_payload(group):
    return {
        "title": "Morning Meditation",
        "description": "A relaxing session",
        "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "duration_minutes": 60,
        "price": "10.00",
        "max_participants": 10,
        "group_id": str(group.id),
    }


# --- List ---


async def test_list_workshops_returns_empty_list(client):
    resp = await client.get("/api/v1/workshops/")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_workshops_returns_created_workshops(
    client, trainer_token, workshop_payload
):
    await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    resp = await client.get(
        "/api/v1/workshops/",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["title"] == workshop_payload["title"]


# --- Create ---


async def test_create_workshop_as_trainer(client, trainer_token, workshop_payload):
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == workshop_payload["title"]
    assert data["max_participants"] == workshop_payload["max_participants"]
    assert "id" in data


async def test_create_workshop_as_regular_user_is_forbidden(
    client, user_token, workshop_payload
):
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


async def test_create_workshop_unauthenticated_is_forbidden(client, workshop_payload):
    resp = await client.post("/api/v1/workshops/", json=workshop_payload)
    assert resp.status_code == 401


async def test_create_workshop_with_invalid_year_is_rejected(
    client, trainer_token, workshop_payload
):
    workshop_payload["start_time"] = "2277-09-01T09:27:00Z"
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 422
    assert "Workshop year must be between" in resp.json()["detail"]


async def test_create_workshop_with_past_date_is_rejected(
    client, trainer_token, workshop_payload
):
    workshop_payload["start_time"] = (
        datetime.now(UTC) - timedelta(hours=2)
    ).isoformat()
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 422
    assert any(
        "future" in str(e.get("msg", "")).lower() for e in resp.json().get("detail", [])
    )


# --- Get ---


async def test_get_workshop_by_id(client, trainer_token, workshop_payload):
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/workshops/{workshop_id}",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == workshop_id


async def test_get_nonexistent_workshop_returns_404(client):
    resp = await client.get("/api/v1/workshops/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# --- Update ---


async def test_update_workshop_title(client, trainer_token, workshop_payload):
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"title": "Evening Meditation"},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Evening Meditation"


async def test_update_workshop_by_non_owner_is_forbidden(
    client, trainer_token, workshop_payload, db_session
):
    other_trainer = User(
        email="other@test.com",
        full_name="Other Trainer",
        google_id="google-other-999",
        role=UserRole.TRAINER,
    )
    db_session.add(other_trainer)
    await db_session.commit()
    await db_session.refresh(other_trainer)
    other_token = create_access_token(other_trainer.id)

    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"title": "Hacked"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403


async def test_update_workshop_with_invalid_year_is_rejected(
    client, trainer_token, workshop_payload
):
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"start_time": "2277-09-01T09:27:00Z"},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 422
    assert "Workshop year must be between" in resp.json()["detail"]


async def test_update_workshop_with_past_date_is_rejected(
    client, trainer_token, workshop_payload
):
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"start_time": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 422
    assert any(
        "future" in str(e.get("msg", "")).lower() for e in resp.json().get("detail", [])
    )


async def test_list_workshops_supports_skip_and_limit(
    client, trainer_token, workshop_payload
):
    payload_1 = {**workshop_payload, "title": "Workshop 1"}
    payload_2 = {
        **workshop_payload,
        "title": "Workshop 2",
        "start_time": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
    }
    payload_3 = {
        **workshop_payload,
        "title": "Workshop 3",
        "start_time": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
    }

    for payload in (payload_1, payload_2, payload_3):
        resp = await client.post(
            "/api/v1/workshops/",
            json=payload,
            headers={"Authorization": f"Bearer {trainer_token}"},
        )
        assert resp.status_code == 201

    headers = {"Authorization": f"Bearer {trainer_token}"}
    first_page = await client.get("/api/v1/workshops/?skip=0&limit=2", headers=headers)
    second_page = await client.get("/api/v1/workshops/?skip=2&limit=2", headers=headers)

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert len(first_page.json()) == 2
    assert len(second_page.json()) == 1


async def test_soft_deleted_workshop_is_not_listed(
    client, trainer_token, workshop_payload
):
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    delete_resp = await client.delete(
        f"/api/v1/workshops/{workshop_id}",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert delete_resp.status_code == 204

    list_resp = await client.get(
        "/api/v1/workshops/",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert list_resp.status_code == 200
    assert all(row["id"] != workshop_id for row in list_resp.json())


# --- Delete ---


async def test_delete_workshop(client, trainer_token, workshop_payload):
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/workshops/{workshop_id}",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 204

    get_resp = await client.get(f"/api/v1/workshops/{workshop_id}")
    assert get_resp.status_code == 404


async def test_delete_live_workshop_returns_409(
    client, trainer_token, trainer, group, db_session
):
    now = datetime.now(UTC).replace(tzinfo=None)
    workshop = Workshop(
        trainer_id=trainer.id,
        group_id=group.id,
        title="Live Workshop",
        start_time=now - timedelta(minutes=5),
        duration_minutes=60,
        max_participants=10,
    )
    db_session.add(workshop)
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/workshops/{workshop.id}",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 409


# --- Date validation ---


async def test_create_workshop_with_past_start_time_is_rejected(
    client, trainer_token, group
):
    past_payload = {
        "title": "Past Workshop",
        "description": "",
        "start_time": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "duration_minutes": 60,
        "price": "0.00",
        "max_participants": 5,
        "group_id": str(group.id),
    }
    resp = await client.post(
        "/api/v1/workshops/",
        json=past_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert any(
        "future" in str(e.get("msg", "")).lower() for e in body.get("detail", [])
    )


async def test_create_workshop_with_future_start_time_succeeds(
    client, trainer_token, workshop_payload
):
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201


async def test_create_workshop_stores_timezone(client, trainer_token, group):
    payload = {
        "title": "LA Evening Session",
        "description": "",
        "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "duration_minutes": 60,
        "timezone": "America/Los_Angeles",
        "price": "0.00",
        "max_participants": 5,
        "group_id": str(group.id),
    }
    resp = await client.post(
        "/api/v1/workshops/",
        json=payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["timezone"] == "America/Los_Angeles"


async def test_create_workshop_defaults_timezone_to_utc(
    client, trainer_token, workshop_payload
):
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["timezone"] == "UTC"


async def test_ongoing_workshop_appears_in_list(
    client, trainer_token, group, db_session
):
    """A workshop that has started but not ended should appear in the list."""
    payload = {
        "title": "Ongoing Session",
        "description": "",
        "start_time": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "duration_minutes": 500,
        "price": "0.00",
        "max_participants": 5,
        "group_id": str(group.id),
    }
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert create_resp.status_code == 201

    workshop = await db_session.get(Workshop, create_resp.json()["id"])
    assert workshop is not None
    workshop.start_time = (datetime.now(UTC) - timedelta(minutes=1)).replace(
        tzinfo=None
    )
    db_session.add(workshop)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/workshops/",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 200
    titles = [w["title"] for w in resp.json()]
    assert "Ongoing Session" in titles


# --- Reminder fields ---


async def test_create_workshop_uses_default_reminder_lead_when_omitted(
    client, trainer_token, workshop_payload
):
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["reminder_minutes_before"] == 60


async def test_create_workshop_accepts_custom_reminder_lead(
    client, trainer_token, workshop_payload
):
    workshop_payload["reminder_minutes_before"] = 15
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["reminder_minutes_before"] == 15


async def test_create_workshop_rejects_negative_reminder_lead(
    client, trainer_token, workshop_payload
):
    workshop_payload["reminder_minutes_before"] = -5
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 422


async def test_update_start_time_rearms_reminder(
    client, trainer_token, workshop_payload, db_session
):
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    workshop = await db_session.get(Workshop, workshop_id)
    workshop.reminder_sent_at = datetime.now(UTC).replace(tzinfo=None)
    db_session.add(workshop)
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"start_time": (datetime.now(UTC) + timedelta(days=2)).isoformat()},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 200

    refreshed = await db_session.get(Workshop, workshop_id)
    await db_session.refresh(refreshed)
    assert refreshed.reminder_sent_at is None


async def test_update_reminder_lead_rearms_when_changed(
    client, trainer_token, workshop_payload, db_session
):
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    workshop = await db_session.get(Workshop, workshop_id)
    workshop.reminder_sent_at = datetime.now(UTC).replace(tzinfo=None)
    db_session.add(workshop)
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"reminder_minutes_before": 30},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["reminder_minutes_before"] == 30

    refreshed = await db_session.get(Workshop, workshop_id)
    await db_session.refresh(refreshed)
    assert refreshed.reminder_sent_at is None


async def test_update_unrelated_field_does_not_rearm_reminder(
    client, trainer_token, workshop_payload, db_session
):
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    sent_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    workshop = await db_session.get(Workshop, workshop_id)
    workshop.reminder_sent_at = sent_at
    db_session.add(workshop)
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"title": "Renamed"},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 200

    refreshed = await db_session.get(Workshop, workshop_id)
    await db_session.refresh(refreshed)
    assert refreshed.reminder_sent_at is not None
    assert refreshed.reminder_sent_at == sent_at
