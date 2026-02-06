from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.user import User, UserRole

router = APIRouter(prefix="/users", tags=["users"])


class UserRead(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_active: bool
    role: UserRole


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
    return user
