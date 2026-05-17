from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from app.models.tag import Tag


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


async def test_create_workshop_extracts_and_persists_tags(
    client, trainer_token, workshop_payload, db_session
):
    workshop_payload["description"] = "Pracujemy nad oddechem #joga #medytacja"
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    assert sorted(resp.json()["tags"]) == ["joga", "medytacja"]

    rows = (await db_session.exec(select(Tag))).all()
    assert sorted(t.name for t in rows) == ["joga", "medytacja"]


async def test_create_workshop_lowercases_and_dedupes_tags(
    client, trainer_token, workshop_payload
):
    workshop_payload["description"] = "#Joga #JOGA #joga and #Yoga"
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["tags"] == ["joga", "yoga"]


async def test_create_workshop_caps_at_five_tags(
    client, trainer_token, workshop_payload
):
    workshop_payload["description"] = "#a1 #b2 #c3 #d4 #e5 #f6 #g7"
    resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["tags"] == ["a1", "b2", "c3", "d4", "e5"]


async def test_tag_is_reused_across_workshops(
    client, trainer_token, workshop_payload, db_session
):
    first = dict(workshop_payload)
    first["description"] = "Working on #joga"
    second = dict(workshop_payload)
    second["title"] = "Another"
    second["description"] = "More #joga and #medytacja"

    r1 = await client.post(
        "/api/v1/workshops/",
        json=first,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    r2 = await client.post(
        "/api/v1/workshops/",
        json=second,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201

    rows = (await db_session.exec(select(Tag))).all()
    assert sorted(t.name for t in rows) == ["joga", "medytacja"]


async def test_update_workshop_description_replaces_tags(
    client, trainer_token, workshop_payload
):
    workshop_payload["description"] = "#joga session"
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"description": "Now only #medytacja"},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["tags"] == ["medytacja"]


async def test_update_workshop_replaces_full_tag_set(
    client, trainer_token, workshop_payload, db_session
):
    """Updating description to a disjoint tag set leaves no stale link rows."""
    workshop_payload["description"] = "#joga and #medytacja"
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"description": "switched to #yoga and #flow"},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert update_resp.status_code == 200
    assert sorted(update_resp.json()["tags"]) == ["flow", "yoga"]

    # Verify link rows in DB exactly match the new set — no stale joga/medytacja
    # entries lingering after the swap.
    from app.models.tag import WorkshopTag
    from uuid import UUID as UUIDType

    rows = (
        await db_session.exec(
            select(WorkshopTag).where(
                WorkshopTag.workshop_id == UUIDType(workshop_id)
            )
        )
    ).all()
    assert len(rows) == 2


async def test_update_workshop_empty_description_clears_tags(
    client, trainer_token, workshop_payload
):
    workshop_payload["description"] = "#joga and #medytacja"
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"description": ""},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["tags"] == []
    assert update_resp.json()["description"] == ""


async def test_update_without_description_keeps_tags(
    client, trainer_token, workshop_payload
):
    workshop_payload["description"] = "#joga and #medytacja"
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"title": "Renamed"},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert update_resp.status_code == 200
    assert sorted(update_resp.json()["tags"]) == ["joga", "medytacja"]


async def test_get_workshop_returns_tags(
    client, trainer_token, workshop_payload
):
    workshop_payload["description"] = "Topic: #joga"
    create_resp = await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    workshop_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/workshops/{workshop_id}")
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["joga"]


async def test_list_workshops_returns_tags(
    client, trainer_token, workshop_payload
):
    workshop_payload["description"] = "Topic: #medytacja"
    await client.post(
        "/api/v1/workshops/",
        json=workshop_payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )

    resp = await client.get("/api/v1/workshops/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["tags"] == ["medytacja"]
