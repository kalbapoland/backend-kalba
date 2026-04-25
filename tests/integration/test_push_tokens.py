import asyncio

from sqlmodel import select

from app.models.notification import PushToken


VALID_TOKEN = "ExponentPushToken[abc123_DEF-456]"
SECOND_TOKEN = "ExponentPushToken[xyz789_GHI-012]"

REGISTER_URL = "/api/v1/users/me/push-tokens"
UNREGISTER_URL = "/api/v1/users/me/push-tokens/unregister"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- PUT /users/me/push-tokens (register) ---


async def test_register_creates_row(client, db_session, user_token, regular_user):
    resp = await client.put(
        REGISTER_URL,
        json={"token": VALID_TOKEN, "platform": "ios"},
        headers=auth(user_token),
    )
    assert resp.status_code == 204

    rows = (await db_session.exec(select(PushToken))).all()
    assert len(rows) == 1
    assert rows[0].token == VALID_TOKEN
    assert rows[0].user_id == regular_user.id
    assert rows[0].platform.value == "ios"


async def test_register_is_idempotent(client, db_session, user_token):
    payload = {"token": VALID_TOKEN, "platform": "android"}
    await client.put(REGISTER_URL, json=payload, headers=auth(user_token))
    resp = await client.put(REGISTER_URL, json=payload, headers=auth(user_token))
    assert resp.status_code == 204

    rows = (await db_session.exec(select(PushToken))).all()
    assert len(rows) == 1


async def test_register_refresh_advances_last_seen_at(client, db_session, user_token):
    """Re-registering the same token refreshes last_seen_at (device heartbeat)."""
    payload = {"token": VALID_TOKEN, "platform": "ios"}
    await client.put(REGISTER_URL, json=payload, headers=auth(user_token))

    first = (await db_session.exec(select(PushToken))).one()
    first_seen = first.last_seen_at

    await asyncio.sleep(0.05)
    await client.put(REGISTER_URL, json=payload, headers=auth(user_token))
    await db_session.refresh(first)

    assert first.last_seen_at > first_seen


async def test_register_two_distinct_tokens_for_same_user_coexist(
    client, db_session, user_token
):
    await client.put(
        REGISTER_URL,
        json={"token": VALID_TOKEN, "platform": "ios"},
        headers=auth(user_token),
    )
    await client.put(
        REGISTER_URL,
        json={"token": SECOND_TOKEN, "platform": "android"},
        headers=auth(user_token),
    )

    rows = (await db_session.exec(select(PushToken))).all()
    assert len(rows) == 2


async def test_register_reassigns_ownership(
    client, db_session, user_token, trainer_token, trainer
):
    """Same device token registered by user A, then by user B → reassigns to B."""
    payload = {"token": VALID_TOKEN, "platform": "ios"}
    await client.put(REGISTER_URL, json=payload, headers=auth(user_token))
    await client.put(REGISTER_URL, json=payload, headers=auth(trainer_token))

    rows = (await db_session.exec(select(PushToken))).all()
    assert len(rows) == 1
    assert rows[0].user_id == trainer.id


async def test_register_rejects_invalid_token_format(client, user_token):
    resp = await client.put(
        REGISTER_URL,
        json={"token": "not-an-expo-token", "platform": "ios"},
        headers=auth(user_token),
    )
    assert resp.status_code == 422


async def test_register_rejects_invalid_platform(client, user_token):
    resp = await client.put(
        REGISTER_URL,
        json={"token": VALID_TOKEN, "platform": "windows"},
        headers=auth(user_token),
    )
    assert resp.status_code == 422


async def test_register_rejects_unknown_fields(client, user_token):
    """ConfigDict(extra='forbid') prevents silent shadowing of body fields."""
    resp = await client.put(
        REGISTER_URL,
        json={"token": VALID_TOKEN, "platform": "ios", "user_id": "evil"},
        headers=auth(user_token),
    )
    assert resp.status_code == 422


async def test_register_requires_auth(client):
    resp = await client.put(
        REGISTER_URL,
        json={"token": VALID_TOKEN, "platform": "ios"},
    )
    assert resp.status_code == 401


# --- POST /users/me/push-tokens/unregister ---


async def test_unregister_removes_row(client, db_session, user_token):
    await client.put(
        REGISTER_URL,
        json={"token": VALID_TOKEN, "platform": "ios"},
        headers=auth(user_token),
    )
    resp = await client.post(
        UNREGISTER_URL,
        json={"token": VALID_TOKEN},
        headers=auth(user_token),
    )
    assert resp.status_code == 204

    rows = (await db_session.exec(select(PushToken))).all()
    assert rows == []


async def test_unregister_is_idempotent(client, user_token):
    resp = await client.post(
        UNREGISTER_URL,
        json={"token": VALID_TOKEN},
        headers=auth(user_token),
    )
    assert resp.status_code == 204


async def test_unregister_other_user_token_is_noop(
    client, db_session, user_token, trainer_token, regular_user
):
    """User A cannot delete user B's token even when knowing the value."""
    await client.put(
        REGISTER_URL,
        json={"token": VALID_TOKEN, "platform": "ios"},
        headers=auth(user_token),
    )
    resp = await client.post(
        UNREGISTER_URL,
        json={"token": VALID_TOKEN},
        headers=auth(trainer_token),
    )
    assert resp.status_code == 204

    rows = (await db_session.exec(select(PushToken))).all()
    assert len(rows) == 1
    assert rows[0].user_id == regular_user.id


async def test_unregister_rejects_invalid_token_format(client, user_token):
    resp = await client.post(
        UNREGISTER_URL,
        json={"token": "garbage"},
        headers=auth(user_token),
    )
    assert resp.status_code == 422


async def test_unregister_requires_auth(client):
    resp = await client.post(UNREGISTER_URL, json={"token": VALID_TOKEN})
    assert resp.status_code == 401
