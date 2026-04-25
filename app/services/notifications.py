"""Push notification service.

Phase 1 covers token registration only; dispatch to Expo Push API will
land in a follow-up commit. See `frontend/docs/DESIGN.md` (Push
Notifications) for the full design.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.notification import PushPlatform, PushToken

logger = logging.getLogger(__name__)


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
    await session.execute(stmt)
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
    await session.execute(stmt)
    await session.commit()
    logger.info("Push token unregister requested by user %s", user_id)
