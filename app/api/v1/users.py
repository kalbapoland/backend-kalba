from uuid import UUID

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import ErrorCode
from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.user import User, UserRead, UserUpdate
from app.services.account import delete_user_account

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
            status_code=status.HTTP_404_NOT_FOUND, detail=ErrorCode.USER_NOT_FOUND
        )
    logger.info("Returning profile for user %s", user_id)
    return user


@router.patch("/me", response_model=UserRead)
async def update_me(
    body: UserUpdate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Update the currently authenticated user's profile (e.g. display name)."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ErrorCode.USER_NOT_FOUND
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    session.add(user)
    await session.commit()
    await session.refresh(user)
    logger.info("User %s updated profile; fields: %s", user_id, ", ".join(update_data) or "none")
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Irreversibly delete the authenticated user's account and all their data.

    Required by Apple App Store Guideline 5.1.1(v). Idempotent-ish: if the user
    is already gone, returns 404.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ErrorCode.USER_NOT_FOUND
        )

    await delete_user_account(user_id, session)
    logger.info("User %s deleted their account", user_id)
