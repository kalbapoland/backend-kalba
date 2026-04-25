from sqlmodel import select

from app.models.notification import PushToken


VALID_TOKEN = "ExponentPushToken[abc123_DEF-456]"
ANOTHER_TOKEN = "ExponentPushToken[xyz789_GHI-012]"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- PUT /users/me/push-tokens ---


async def test_register_push_token_creates_row(client, db_session, user_token, regular_user):
    resp = await client.put(
        "/api/v1/users/me/push-tokens",
        json={"token": VALID_TOKEN, "platform": "ios"},
        headers=auth(user_token),
    )
    assert resp.status_code == 200

    rows = (await db_session.exec(select(PushToken))).all()
    assert len(rows) == 1
    assert rows[0].token == VALID_TOKEN
    assert rows[0].user_id == regular_user.id
    assert rows[0].platform.value == "ios"


async def test_register_push_token_is_idempotent(client, db_session, user_token):
    payload = {"token": VALID_TOKEN, "platform": "android"}
    await client.put("/api/v1/users/me/push-tokens", json=payload, headers=auth(user_token))
    resp = await client.put("/api/v1/users/me/push-tokens", json=payload, headers=auth(user_token))
    assert resp.status_code == 200

    rows = (await db_session.exec(select(PushToken))).all()
    assert len(rows) == 1


async def test_register_push_token_reassigns_ownership(
    client, db_session, user_token, trainer_token, regular_user, trainer
):
    """Same device token registered by user A, then by user B → reassigns to B."""
    payload = {"token": VALID_TOKEN, "platform": "ios"}
    await client.put("/api/v1/users/me/push-tokens", json=payload, headers=auth(user_token))
    await client.put("/api/v1/users/me/push-tokens", json=payload, headers=auth(trainer_token))

    rows = (await db_session.exec(select(PushToken))).all()
    assert len(rows) == 1
    assert rows[0].user_id == trainer.id


async def test_register_push_token_rejects_invalid_format(client, user_token):
    resp = await client.put(
        "/api/v1/users/me/push-tokens",
        json={"token": "not-an-expo-token", "platform": "ios"},
        headers=auth(user_token),
    )
    assert resp.status_code == 422


async def test_register_push_token_rejects_invalid_platform(client, user_token):
    resp = await client.put(
        "/api/v1/users/me/push-tokens",
        json={"token": VALID_TOKEN, "platform": "windows"},
        headers=auth(user_token),
    )
    assert resp.status_code == 422


async def test_register_push_token_requires_auth(client):
    resp = await client.put(
        "/api/v1/users/me/push-tokens",
        json={"token": VALID_TOKEN, "platform": "ios"},
    )
    assert resp.status_code == 401


# --- DELETE /users/me/push-tokens/{token} ---


async def test_delete_push_token_removes_row(client, db_session, user_token):
    await client.put(
        "/api/v1/users/me/push-tokens",
        json={"token": VALID_TOKEN, "platform": "ios"},
        headers=auth(user_token),
    )
    resp = await client.delete(
        f"/api/v1/users/me/push-tokens/{VALID_TOKEN}", headers=auth(user_token)
    )
    assert resp.status_code == 204

    rows = (await db_session.exec(select(PushToken))).all()
    assert rows == []


async def test_delete_push_token_is_idempotent(client, user_token):
    resp = await client.delete(
        f"/api/v1/users/me/push-tokens/{VALID_TOKEN}", headers=auth(user_token)
    )
    assert resp.status_code == 204


async def test_delete_push_token_other_user_token_is_noop(
    client, db_session, user_token, trainer_token, regular_user
):
    """User A cannot delete user B's token even when knowing the value."""
    await client.put(
        "/api/v1/users/me/push-tokens",
        json={"token": VALID_TOKEN, "platform": "ios"},
        headers=auth(user_token),
    )
    resp = await client.delete(
        f"/api/v1/users/me/push-tokens/{VALID_TOKEN}", headers=auth(trainer_token)
    )
    assert resp.status_code == 204

    rows = (await db_session.exec(select(PushToken))).all()
    assert len(rows) == 1
    assert rows[0].user_id == regular_user.id


async def test_delete_push_token_invalid_format_returns_204(client, user_token):
    """Malformed token paths are treated as no-op deletes (no info leakage)."""
    resp = await client.delete(
        "/api/v1/users/me/push-tokens/garbage", headers=auth(user_token)
    )
    assert resp.status_code == 204


async def test_delete_push_token_requires_auth(client):
    resp = await client.delete(f"/api/v1/users/me/push-tokens/{VALID_TOKEN}")
    assert resp.status_code == 401
