from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.user import User, UserRole
from app.models.workshop import Workshop

router = APIRouter(prefix="/workshops", tags=["workshops"])


class WorkshopCreate(BaseModel):
    title: str
    description: str = ""
    start_time: datetime
    duration_minutes: int
    price: Decimal = Decimal("0.00")
    max_participants: int


class WorkshopRead(BaseModel):
    id: UUID
    trainer_id: UUID
    title: str
    description: str
    start_time: datetime
    duration_minutes: int
    price: Decimal
    max_participants: int


@router.get("/", response_model=list[WorkshopRead])
async def list_workshops(
    session: AsyncSession = Depends(get_db_session),
):
    """List all upcoming workshops."""
    statement = select(Workshop).where(Workshop.start_time >= datetime.utcnow())
    result = await session.exec(statement)
    return result.all()


@router.post("/", response_model=WorkshopRead, status_code=status.HTTP_201_CREATED)
async def create_workshop(
    body: WorkshopCreate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new workshop. Only trainers may create workshops."""
    user = await session.get(User, user_id)
    if user is None or user.role != UserRole.TRAINER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only trainers can create workshops",
        )

    workshop = Workshop(
        trainer_id=user_id,
        title=body.title,
        description=body.description,
        start_time=body.start_time,
        duration_minutes=body.duration_minutes,
        price=body.price,
        max_participants=body.max_participants,
    )
    session.add(workshop)
    await session.commit()
    await session.refresh(workshop)
    return workshop
