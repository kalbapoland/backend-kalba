"""End-to-end tests for `send_push_to_users`.

Uses real Postgres (via the integration conftest) and a mocked httpx
transport so no network calls leave the test process.
"""

import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlmodel import select

from app.core.config import Settings
from app.models.notification import PushPlatform, PushToken
from app.services.notifications import (
    EXPO_BATCH_SIZE,
    PushMessage,
    register_push_token,
    send_push_to_users,
)


VALID_TOKEN_TPL = "ExponentPushToken[{}]"


def _settings(*, access_token: str = "") -> Settings:
    return Settings(
        expo_push_url="https://exp.host/--/api/v2/push/send",
        expo_push_access_token=access_token,
    )


def _ok_response(payload: list[dict[str, Any]]) -> httpx.Response:
    """Build an Expo-shaped success response for the given outbound batch."""
    data = [{"status": "ok", "id": f"ticket-{i}"} for i, _ in enumerate(payload)]
    return httpx.Response(200, json={"data": data})


async def _register(session, user_id: UUID, suffix: str) -> str:
    token = VALID_TOKEN_TPL.format(suffix)
    await register_push_token(
        session, user_id=user_id, token=token, platform=PushPlatform.IOS
    )
    return token


# --- Empty-input short-circuits ---


async def test_send_to_empty_user_list_makes_no_request(db_session):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ok_response([])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await send_push_to_users(
            db_session,
            user_ids=[],
            message=PushMessage(title="t", body="b"),
            settings=_settings(),
            http_client=client,
        )

    assert result.sent == 0
    assert calls == []


async def test_send_to_users_with_no_tokens_makes_no_request(
    db_session, regular_user
):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ok_response([])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await send_push_to_users(
            db_session,
            user_ids=[regular_user.id],
            message=PushMessage(title="t", body="b"),
            settings=_settings(),
            http_client=client,
        )

    assert result.sent == 0
    assert calls == []


# --- Happy path ---


async def test_send_dispatches_one_token_and_marks_sent(db_session, regular_user):
    token = await _register(db_session, regular_user.id, "abcd1234")

    captured: list[list[dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _ok_response(captured[-1])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await send_push_to_users(
            db_session,
            user_ids=[regular_user.id],
            message=PushMessage(title="Hi", body="Body", data={"k": "v"}),
            settings=_settings(),
            http_client=client,
        )

    assert result.sent == 1
    assert result.invalidated == 0
    assert result.failed == 0
    assert len(captured) == 1
    assert captured[0] == [
        {
            "to": token,
            "title": "Hi",
            "body": "Body",
            "sound": "default",
            "data": {"k": "v"},
        }
    ]


async def test_send_includes_authorization_header_when_access_token_set(
    db_session, regular_user
):
    await _register(db_session, regular_user.id, "abcd1234")
    headers_seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        headers_seen.update(request.headers)
        return _ok_response(json.loads(request.content))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await send_push_to_users(
            db_session,
            user_ids=[regular_user.id],
            message=PushMessage(title="t", body="b"),
            settings=_settings(access_token="secret-token"),
            http_client=client,
        )

    assert headers_seen.get("authorization") == "Bearer secret-token"


async def test_send_omits_authorization_header_when_no_access_token(
    db_session, regular_user
):
    await _register(db_session, regular_user.id, "abcd1234")
    headers_seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        headers_seen.update(request.headers)
        return _ok_response(json.loads(request.content))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await send_push_to_users(
            db_session,
            user_ids=[regular_user.id],
            message=PushMessage(title="t", body="b"),
            settings=_settings(),
            http_client=client,
        )

    assert "authorization" not in headers_seen


# --- Batching ---


@pytest.mark.parametrize("token_count", [EXPO_BATCH_SIZE + 1, EXPO_BATCH_SIZE * 2 + 5])
async def test_send_splits_into_batches_of_max_size(
    db_session, regular_user, token_count: int
):
    for i in range(token_count):
        await _register(db_session, regular_user.id, f"tok{i:08d}")

    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        batch_sizes.append(len(body))
        return _ok_response(body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await send_push_to_users(
            db_session,
            user_ids=[regular_user.id],
            message=PushMessage(title="t", body="b"),
            settings=_settings(),
            http_client=client,
        )

    assert sum(batch_sizes) == token_count
    assert max(batch_sizes) <= EXPO_BATCH_SIZE
    assert result.sent == token_count


# --- DeviceNotRegistered cleanup ---


async def test_device_not_registered_token_is_deleted(db_session, regular_user):
    good = await _register(db_session, regular_user.id, "goodtok1")
    bad = await _register(db_session, regular_user.id, "badtok99")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        data = []
        for entry in body:
            if entry["to"] == bad:
                data.append(
                    {
                        "status": "error",
                        "message": "device gone",
                        "details": {"error": "DeviceNotRegistered"},
                    }
                )
            else:
                data.append({"status": "ok", "id": "ticket"})
        return httpx.Response(200, json={"data": data})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await send_push_to_users(
            db_session,
            user_ids=[regular_user.id],
            message=PushMessage(title="t", body="b"),
            settings=_settings(),
            http_client=client,
        )

    assert result.sent == 1
    assert result.invalidated == 1
    assert result.failed == 0

    remaining = (await db_session.exec(select(PushToken.token))).all()
    assert good in remaining
    assert bad not in remaining


# --- Other Expo errors ---


async def test_other_expo_error_is_failed_and_keeps_token(
    db_session, regular_user
):
    token = await _register(db_session, regular_user.id, "kepme123")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "status": "error",
                        "message": "too big",
                        "details": {"error": "MessageTooBig"},
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await send_push_to_users(
            db_session,
            user_ids=[regular_user.id],
            message=PushMessage(title="t", body="b"),
            settings=_settings(),
            http_client=client,
        )

    assert result.failed == 1
    assert result.invalidated == 0

    remaining = (await db_session.exec(select(PushToken.token))).all()
    assert token in remaining


# --- Transport errors ---


async def test_transport_error_marks_all_failed_and_keeps_tokens(
    db_session, regular_user
):
    token = await _register(db_session, regular_user.id, "stillhere")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await send_push_to_users(
            db_session,
            user_ids=[regular_user.id],
            message=PushMessage(title="t", body="b"),
            settings=_settings(),
            http_client=client,
        )

    assert result.sent == 0
    assert result.invalidated == 0
    assert result.failed == 1

    remaining = (await db_session.exec(select(PushToken.token))).all()
    assert token in remaining


async def test_5xx_response_marks_all_failed_and_keeps_tokens(
    db_session, regular_user
):
    token = await _register(db_session, regular_user.id, "stillthr")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await send_push_to_users(
            db_session,
            user_ids=[regular_user.id],
            message=PushMessage(title="t", body="b"),
            settings=_settings(),
            http_client=client,
        )

    assert result.failed == 1

    remaining = (await db_session.exec(select(PushToken.token))).all()
    assert token in remaining
