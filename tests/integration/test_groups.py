from datetime import UTC, datetime, timedelta

import pytest

import app.api.v1.groups as _groups_module
from app.core.security import create_access_token
from app.models.group import Group
from app.models.user import User, UserRole
from app.models.workshop import Workshop
from app.services.notifications import DispatchResult, PushMessage


@pytest.fixture
def group_payload():
    return {"title": "Morning Crew", "description": "Daily movement #flow"}


async def _create_group(client, token, payload):
    resp = await client.post(
        "/api/v1/groups/",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _make_user(db_session, *, email, google_id, role=UserRole.USER):
    user = User(email=email, full_name=email.split("@")[0], google_id=google_id, role=role)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# --- POST /groups/ (create) ---


async def test_create_group_trainer_ok(client, trainer_token, group_payload):
    body = await _create_group(client, trainer_token, group_payload)
    assert body["title"] == "Morning Crew"
    assert body["is_owner"] is True
    assert body["is_member"] is False
    assert body["member_count"] == 0


async def test_create_group_user_forbidden(client, user_token, group_payload):
    resp = await client.post(
        "/api/v1/groups/",
        json=group_payload,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


async def test_create_group_unauthenticated(client, group_payload):
    resp = await client.post("/api/v1/groups/", json=group_payload)
    assert resp.status_code == 401


# --- GET /groups/ and /groups/{id} (read + caller context) ---


async def test_list_groups_sets_caller_context(
    client, trainer_token, user_token, group_payload
):
    group = await _create_group(client, trainer_token, group_payload)
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # Before subscribing: visible, not member, not owner.
    resp = await client.get("/api/v1/groups/", headers=user_headers)
    assert resp.status_code == 200
    row = next(g for g in resp.json() if g["id"] == group["id"])
    assert row["is_owner"] is False
    assert row["is_member"] is False

    await client.post(f"/api/v1/groups/{group['id']}/subscribe", headers=user_headers)
    resp = await client.get("/api/v1/groups/", headers=user_headers)
    row = next(g for g in resp.json() if g["id"] == group["id"])
    assert row["is_member"] is True
    assert row["member_count"] == 1


async def test_get_group_not_found(client, user_token):
    resp = await client.get(
        "/api/v1/groups/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 404


async def test_get_soft_deleted_group_returns_404(
    client, trainer_token, group_payload, db_session
):
    group = await _create_group(client, trainer_token, group_payload)
    row = await db_session.get(Group, group["id"])
    row.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    db_session.add(row)
    await db_session.commit()

    resp = await client.get(f"/api/v1/groups/{group['id']}")
    assert resp.status_code == 404


# --- GET /groups/mine ---


async def test_mine_returns_owned_and_subscribed(
    client, trainer_token, user_token, group_payload, db_session
):
    owned = await _create_group(client, trainer_token, group_payload)

    # A second trainer owns another group that our user subscribes to.
    other_trainer = await _make_user(
        db_session, email="t2@test.com", google_id="g-t2", role=UserRole.TRAINER
    )
    other_token = create_access_token(other_trainer.id)
    subscribed = await _create_group(
        client, other_token, {"title": "Evening", "description": ""}
    )

    user_headers = {"Authorization": f"Bearer {user_token}"}
    await client.post(
        f"/api/v1/groups/{subscribed['id']}/subscribe", headers=user_headers
    )

    # User's /mine → only the subscribed group.
    resp = await client.get("/api/v1/groups/mine", headers=user_headers)
    assert resp.status_code == 200
    assert {g["title"] for g in resp.json()} == {"Evening"}

    # Owner trainer's /mine → their owned group.
    resp = await client.get(
        "/api/v1/groups/mine", headers={"Authorization": f"Bearer {trainer_token}"}
    )
    titles = {g["title"] for g in resp.json()}
    assert "Morning Crew" in titles
    assert owned["id"] in {g["id"] for g in resp.json()}


async def test_mine_requires_auth(client):
    resp = await client.get("/api/v1/groups/mine")
    assert resp.status_code == 401


# --- PATCH /groups/{id} ---


async def test_update_group_owner_ok(client, trainer_token, group_payload):
    group = await _create_group(client, trainer_token, group_payload)
    resp = await client.patch(
        f"/api/v1/groups/{group['id']}",
        json={"description": "Updated focus"},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated focus"


async def test_update_group_non_owner_forbidden(
    client, trainer_token, group_payload, db_session
):
    group = await _create_group(client, trainer_token, group_payload)
    other_trainer = await _make_user(
        db_session, email="t3@test.com", google_id="g-t3", role=UserRole.TRAINER
    )
    other_token = create_access_token(other_trainer.id)
    resp = await client.patch(
        f"/api/v1/groups/{group['id']}",
        json={"title": "Hijack"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403


async def test_update_group_by_regular_user_forbidden(
    client, trainer_token, user_token, group_payload
):
    group = await _create_group(client, trainer_token, group_payload)
    resp = await client.patch(
        f"/api/v1/groups/{group['id']}",
        json={"title": "Nope"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


# --- DELETE /groups/{id} ---


async def test_delete_group_with_live_workshop_returns_409(
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
        f"/api/v1/groups/{group.id}",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 409


async def test_delete_group_owner_soft_deletes(client, trainer_token, group_payload):
    group = await _create_group(client, trainer_token, group_payload)
    headers = {"Authorization": f"Bearer {trainer_token}"}
    resp = await client.delete(f"/api/v1/groups/{group['id']}", headers=headers)
    assert resp.status_code == 204

    # Now invisible.
    assert (await client.get(f"/api/v1/groups/{group['id']}")).status_code == 404


async def test_delete_group_non_owner_forbidden(
    client, trainer_token, user_token, group_payload
):
    group = await _create_group(client, trainer_token, group_payload)
    resp = await client.delete(
        f"/api/v1/groups/{group['id']}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


@pytest.fixture
def stub_push(monkeypatch):
    """Prevent real Expo HTTP calls; capture payloads for assertion."""
    calls: list[dict] = []

    async def fake_send(session, *, user_ids, message: PushMessage, **_kw):
        calls.append(
            {
                "user_ids": list(user_ids),
                "title": message.title,
                "body": message.body,
                "data": message.data,
            }
        )
        return DispatchResult(sent=len(user_ids), invalidated=0, failed=0)

    monkeypatch.setattr(_groups_module, "send_push_to_users", fake_send)
    return calls


async def test_delete_group_notifies_subscribers(
    client, trainer_token, user_token, group_payload, regular_user, stub_push
):
    group = await _create_group(client, trainer_token, group_payload)
    user_headers = {"Authorization": f"Bearer {user_token}"}
    await client.post(f"/api/v1/groups/{group['id']}/subscribe", headers=user_headers)

    resp = await client.delete(
        f"/api/v1/groups/{group['id']}",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 204

    notif_resp = await client.get(
        "/api/v1/users/me/my-kalba/notifications?unread_only=true",
        headers=user_headers,
    )
    assert notif_resp.status_code == 200
    notifications = notif_resp.json()
    assert len(notifications) == 1
    assert notifications[0]["type"] == "group_deleted"
    assert notifications[0]["payload"]["group_id"] == group["id"]

    assert len(stub_push) == 1
    assert stub_push[0]["data"] == {"group_id": group["id"], "type": "deleted"}
    assert group_payload["title"] in stub_push[0]["body"]


async def test_delete_group_without_subscribers_creates_no_notification(
    client, trainer_token, user_token, group_payload, stub_push
):
    group = await _create_group(client, trainer_token, group_payload)

    resp = await client.delete(
        f"/api/v1/groups/{group['id']}",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 204

    notif_resp = await client.get(
        "/api/v1/users/me/my-kalba/notifications?unread_only=true",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert notif_resp.status_code == 200
    assert notif_resp.json() == []
    assert stub_push == []


async def test_delete_group_cascades_workshops(
    client, trainer_token, user_token, group, regular_user, subscribe, stub_push
):
    """Deleting a group soft-deletes its workshops and notifies enrolled users."""
    trainer_headers = {"Authorization": f"Bearer {trainer_token}"}
    user_headers = {"Authorization": f"Bearer {user_token}"}

    await subscribe(group, regular_user)

    workshop_resp = await client.post(
        "/api/v1/workshops/",
        json={
            "title": "Cascade Workshop",
            "description": "",
            "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "duration_minutes": 60,
            "price": "0.00",
            "max_participants": 10,
            "group_id": str(group.id),
        },
        headers=trainer_headers,
    )
    assert workshop_resp.status_code == 201
    workshop_id = workshop_resp.json()["id"]

    enroll_resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers=user_headers,
    )
    assert enroll_resp.status_code == 200

    del_resp = await client.delete(
        f"/api/v1/groups/{group.id}",
        headers=trainer_headers,
    )
    assert del_resp.status_code == 204

    # Workshop should be gone.
    assert (await client.get(f"/api/v1/workshops/{workshop_id}")).status_code == 404

    # User should have both workshop_cancelled and group_deleted in-app notifications.
    notif_resp = await client.get(
        "/api/v1/users/me/my-kalba/notifications?unread_only=true",
        headers=user_headers,
    )
    assert notif_resp.status_code == 200
    notif_types = {n["type"] for n in notif_resp.json()}
    assert "workshop_cancelled" in notif_types
    assert "group_deleted" in notif_types

    # Push goes out only for group deletion (not per-workshop on cascade).
    assert len(stub_push) == 1
    assert stub_push[0]["data"]["type"] == "deleted"


# --- subscribe / unsubscribe ---


async def test_subscribe_happy_path(client, trainer_token, user_token, group_payload):
    group = await _create_group(client, trainer_token, group_payload)
    resp = await client.post(
        f"/api/v1/groups/{group['id']}/subscribe",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_member"] is True
    assert body["member_count"] == 1


async def test_subscribe_is_idempotent(
    client, trainer_token, user_token, group_payload
):
    group = await _create_group(client, trainer_token, group_payload)
    headers = {"Authorization": f"Bearer {user_token}"}
    first = await client.post(f"/api/v1/groups/{group['id']}/subscribe", headers=headers)
    second = await client.post(f"/api/v1/groups/{group['id']}/subscribe", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["member_count"] == 1


async def test_owner_cannot_subscribe_to_own_group(
    client, trainer_token, group_payload
):
    group = await _create_group(client, trainer_token, group_payload)
    resp = await client.post(
        f"/api/v1/groups/{group['id']}/subscribe",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 400


async def test_trainer_subscriber_role_recorded(
    client, trainer_token, group_payload, db_session
):
    group = await _create_group(client, trainer_token, group_payload)
    # A different trainer subscribes as a regular member.
    other_trainer = await _make_user(
        db_session, email="t4@test.com", google_id="g-t4", role=UserRole.TRAINER
    )
    other_token = create_access_token(other_trainer.id)
    resp = await client.post(
        f"/api/v1/groups/{group['id']}/subscribe",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 200

    members = await client.get(f"/api/v1/groups/{group['id']}/members")
    roles = {m["user_id"]: m["role"] for m in members.json()}
    assert roles[str(other_trainer.id)] == "trainer_subscriber"


async def test_unsubscribe_happy_and_idempotent(
    client, trainer_token, user_token, group_payload
):
    group = await _create_group(client, trainer_token, group_payload)
    headers = {"Authorization": f"Bearer {user_token}"}
    await client.post(f"/api/v1/groups/{group['id']}/subscribe", headers=headers)

    resp = await client.post(f"/api/v1/groups/{group['id']}/unsubscribe", headers=headers)
    assert resp.status_code == 204
    # Idempotent — second call still 204.
    again = await client.post(
        f"/api/v1/groups/{group['id']}/unsubscribe", headers=headers
    )
    assert again.status_code == 204

    detail = await client.get(f"/api/v1/groups/{group['id']}", headers=headers)
    assert detail.json()["is_member"] is False
    assert detail.json()["member_count"] == 0


# --- members management ---


async def test_owner_can_remove_member(
    client, trainer_token, user_token, regular_user, group_payload
):
    group = await _create_group(client, trainer_token, group_payload)
    user_headers = {"Authorization": f"Bearer {user_token}"}
    await client.post(f"/api/v1/groups/{group['id']}/subscribe", headers=user_headers)

    resp = await client.delete(
        f"/api/v1/groups/{group['id']}/members/{regular_user.id}",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 204

    detail = await client.get(f"/api/v1/groups/{group['id']}", headers=user_headers)
    assert detail.json()["is_member"] is False


async def test_non_owner_cannot_remove_member(
    client, trainer_token, user_token, regular_user, group_payload
):
    group = await _create_group(client, trainer_token, group_payload)
    user_headers = {"Authorization": f"Bearer {user_token}"}
    await client.post(f"/api/v1/groups/{group['id']}/subscribe", headers=user_headers)

    # The member tries to remove themselves via the admin endpoint → 403.
    resp = await client.delete(
        f"/api/v1/groups/{group['id']}/members/{regular_user.id}",
        headers=user_headers,
    )
    assert resp.status_code == 403


# --- workshop <-> group link ---


def _workshop_payload(**overrides):
    payload = {
        "title": "Group Session",
        "description": "",
        "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "duration_minutes": 60,
        "price": "0.00",
        "max_participants": 10,
    }
    payload.update(overrides)
    return payload


async def test_attach_workshop_to_own_group_lists_it(
    client, trainer_token, group_payload
):
    group = await _create_group(client, trainer_token, group_payload)
    headers = {"Authorization": f"Bearer {trainer_token}"}
    resp = await client.post(
        "/api/v1/workshops/",
        json=_workshop_payload(group_id=group["id"]),
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["group_id"] == group["id"]

    listed = await client.get(
        f"/api/v1/groups/{group['id']}/workshops", headers=headers
    )
    assert listed.status_code == 200
    assert {w["id"] for w in listed.json()} == {resp.json()["id"]}


async def test_attach_workshop_to_foreign_group_forbidden(
    client, trainer_token, group_payload, db_session
):
    # Group owned by a different trainer.
    other_trainer = await _make_user(
        db_session, email="t5@test.com", google_id="g-t5", role=UserRole.TRAINER
    )
    other_token = create_access_token(other_trainer.id)
    foreign = await _create_group(
        client, other_token, {"title": "Theirs", "description": ""}
    )

    resp = await client.post(
        "/api/v1/workshops/",
        json=_workshop_payload(group_id=foreign["id"]),
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 403
