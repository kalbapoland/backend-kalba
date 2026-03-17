from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import create_access_token
from app.models.user import User, UserRole


@pytest.fixture
def workshop_payload():
    return {
        "title": "Morning Meditation",
        "description": "A relaxing session",
        "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "duration_minutes": 60,
        "price": "10.00",
        "max_participants": 10,
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
    resp = await client.get("/api/v1/workshops/")
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


# --- Get ---


async def test_get_workshop_by_id(client, trainer_token, workshop_payload):
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/workshops/{workshop_id}")
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
