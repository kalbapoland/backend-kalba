from datetime import datetime
from uuid import UUID

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.notification import EXPO_TOKEN_PATTERN, PushToken, PushTokenRegister
from app.models.user import User, UserRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def get_me(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Return the currently authenticated user's profile."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    logger.info("Returning profile for user %s", user_id)
    return user


@router.put("/me/push-tokens", status_code=status.HTTP_200_OK)
async def register_push_token(
    body: PushTokenRegister,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Register or refresh a push token for the current user.

    Idempotent upsert keyed on token. If the token is already registered
    to a different user (shared device, account switch), ownership is
    reassigned to the current user — tokens belong to devices, not users.
    """
    now = datetime.utcnow()
    stmt = pg_insert(PushToken).values(
        user_id=user_id,
        token=body.token,
        platform=body.platform,
        created_at=now,
        last_seen_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["token"],
        set_={"user_id": user_id, "last_seen_at": now},
    )
    await session.execute(stmt)
    await session.commit()
    logger.info("Push token upserted for user %s on %s", user_id, body.platform.value)
    return {"status": "ok"}


@router.delete("/me/push-tokens/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_push_token(
    token: str = Path(...),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Unregister a push token for the current user (e.g. on logout).

    Idempotent: returns 204 even when the token does not exist or belongs
    to a different user (no info leakage about token ownership).
    """
    if not EXPO_TOKEN_PATTERN.match(token):
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    stmt = delete(PushToken).where(
        PushToken.token == token, PushToken.user_id == user_id
    )
    await session.execute(stmt)
    await session.commit()
    logger.info("Push token delete requested by user %s", user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
