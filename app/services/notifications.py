"""Push notification service — registration + Expo Push dispatch.

Dispatch wraps Expo's push service (https://docs.expo.dev/push-notifications/sending-notifications/).
Tokens that come back as `DeviceNotRegistered` are deleted from the DB on
the same call so the next dispatch does not retry them. Other Expo
errors are logged but tokens are kept (transient or recoverable).

See `frontend/docs/DESIGN.md` (Push Notifications) for the full design.
"""

import logging
from collections.abc import Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.models.notification import PushPlatform, PushToken

logger = logging.getLogger(__name__)

EXPO_BATCH_SIZE = 100  # Expo Push API limit per request
EXPO_REQUEST_TIMEOUT_S = 10.0


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# --- Token registration --------------------------------------------------


async def register_push_token(
    session: AsyncSession,
    *,
    user_id: UUID,
    token: str,
    platform: PushPlatform,
) -> None:
    """Upsert a push token for the given user.

    Atomic via PostgreSQL `INSERT ... ON CONFLICT (token) DO UPDATE`. If
    the token already exists under another user (shared device, account
    switch), ownership is reassigned — tokens belong to devices, not
    users.
    """
    now = _utc_now_naive()
    stmt = pg_insert(PushToken).values(
        user_id=user_id,
        token=token,
        platform=platform,
        created_at=now,
        last_seen_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["token"],
        set_={"user_id": user_id, "last_seen_at": now},
    )
    await session.exec(stmt)
    await session.commit()
    logger.info("Push token upserted for user %s on %s", user_id, platform.value)


async def unregister_push_token(
    session: AsyncSession,
    *,
    user_id: UUID,
    token: str,
) -> None:
    """Delete a push token, scoped to the current user.

    Cross-user delete is prevented by the `user_id` predicate — knowing
    the token value is not enough to remove someone else's row. No-op
    when the token does not exist (idempotent on logout).
    """
    stmt = delete(PushToken).where(
        PushToken.token == token, PushToken.user_id == user_id
    )
    await session.exec(stmt)
    await session.commit()
    logger.info("Push token unregister requested by user %s", user_id)


# --- Expo Push dispatch --------------------------------------------------


@dataclass(frozen=True)
class PushMessage:
    """A single push notification payload."""

    title: str
    body: str
    data: dict[str, Any] | None = None


@dataclass
class DispatchResult:
    """Outcome of a single dispatch call (one or many recipients)."""

    sent: int = 0
    invalidated: int = 0  # tokens deleted because Expo returned DeviceNotRegistered
    failed: int = 0  # other Expo errors; token kept


async def send_push_to_users(
    session: AsyncSession,
    *,
    user_ids: Sequence[UUID],
    message: PushMessage,
    settings: Settings | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> DispatchResult:
    """Dispatch one push message to all tokens owned by the given users.

    - Looks up every token for the supplied users in one query.
    - Batches into groups of `EXPO_BATCH_SIZE` and POSTs each batch to
      Expo Push API.
    - For tokens whose ticket comes back with `DeviceNotRegistered`,
      removes them from the DB so future calls skip them.
    - Returns a `DispatchResult` with counters for observability.

    The `http_client` parameter is for tests — production callers should
    leave it `None` and let the function manage its own client lifecycle.
    """
    if not user_ids:
        return DispatchResult()

    settings = settings or get_settings()

    tokens = await _load_tokens_for_users(session, user_ids)
    if not tokens:
        return DispatchResult()

    result = DispatchResult()
    invalid_tokens: list[str] = []

    async with _http_context(http_client) as client:
        for batch in _chunks(tokens, EXPO_BATCH_SIZE):
            payload = [_build_message(t, message) for t in batch]
            tickets = await _post_to_expo(client, settings, payload)
            counts, invalid = _classify_tickets(batch, tickets)
            result.sent += counts.sent
            result.invalidated += counts.invalidated
            result.failed += counts.failed
            invalid_tokens.extend(invalid)

    if invalid_tokens:
        await _delete_tokens(session, invalid_tokens)

    logger.info(
        "Push dispatch: sent=%d invalidated=%d failed=%d",
        result.sent,
        result.invalidated,
        result.failed,
    )
    return result


# --- Internals -----------------------------------------------------------


async def _load_tokens_for_users(
    session: AsyncSession, user_ids: Sequence[UUID]
) -> list[str]:
    stmt = select(PushToken.token).where(PushToken.user_id.in_(user_ids))
    rows = await session.exec(stmt)
    return list(rows.all())


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _build_message(token: str, message: PushMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "to": token,
        "title": message.title,
        "body": message.body,
        "sound": "default",
    }
    if message.data is not None:
        payload["data"] = message.data
    return payload


def _http_context(
    http_client: httpx.AsyncClient | None,
) -> AbstractAsyncContextManager[httpx.AsyncClient]:
    """Return a context manager yielding an AsyncClient.

    When the caller supplies one (tests), do not close it; otherwise own
    the lifecycle.
    """
    if http_client is not None:
        return _BorrowedClient(http_client)
    return httpx.AsyncClient(timeout=EXPO_REQUEST_TIMEOUT_S)


class _BorrowedClient:
    """Context manager that yields a borrowed client without closing it."""

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


async def _post_to_expo(
    client: httpx.AsyncClient,
    settings: Settings,
    payload: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """POST a batch to Expo. Returns the `data` array from the response.

    Returns an empty list and logs on transport / 5xx error so the caller
    treats the batch as failed (tokens kept) — a future scheduler can
    retry on its next tick.
    """
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.expo_push_access_token:
        headers["Authorization"] = f"Bearer {settings.expo_push_access_token}"

    try:
        response = await client.post(settings.expo_push_url, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Expo push request failed: %s", exc)
        return []

    body = response.json()
    return body.get("data", []) or []


@dataclass
class _BatchCounts:
    sent: int = 0
    invalidated: int = 0
    failed: int = 0


def _classify_tickets(
    tokens: Sequence[str], tickets: Sequence[dict[str, Any]]
) -> tuple[_BatchCounts, list[str]]:
    """Map Expo tickets back to tokens; collect tokens to delete."""
    counts = _BatchCounts()
    invalid: list[str] = []

    if len(tickets) != len(tokens):
        # Transport error returned [] earlier, or Expo returned a partial
        # payload. Treat all tokens as failed (kept) — safer than guessing
        # alignment. Warn on partial because Expo's contract is "data array
        # of equal length on 200" — drift is worth seeing.
        if tickets:
            logger.warning(
                "Expo returned %d tickets for %d tokens; treating batch as failed",
                len(tickets),
                len(tokens),
            )
        counts.failed = len(tokens)
        return counts, invalid

    for token, ticket in zip(tokens, tickets, strict=True):
        if ticket.get("status") == "ok":
            counts.sent += 1
            continue

        details = ticket.get("details") or {}
        if details.get("error") == "DeviceNotRegistered":
            counts.invalidated += 1
            invalid.append(token)
            continue

        counts.failed += 1
        logger.warning(
            "Expo push error for token=%s message=%s",
            _redact_token(token),
            ticket.get("message"),
        )

    return counts, invalid


def _redact_token(token: str) -> str:
    """Log-safe token shape — last 4 of the inner id only."""
    if "[" in token and token.endswith("]"):
        inner = token[token.index("[") + 1 : -1]
        return f"ExponentPushToken[...{inner[-4:]}]" if len(inner) >= 4 else "ExponentPushToken[...]"
    return "<malformed>"


async def _delete_tokens(session: AsyncSession, tokens: Sequence[str]) -> None:
    stmt = delete(PushToken).where(PushToken.token.in_(tokens))
    await session.exec(stmt)
    await session.commit()
    logger.info("Removed %d Expo-invalidated tokens", len(tokens))
