import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.user import User, UserRole
from app.models.video import WorkshopRules
from app.models.workshop import Workshop, WorkshopCreate, WorkshopRead
from app.services.daily import DailyService, DailyServiceError, get_daily_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workshops", tags=["workshops"])


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
    daily: DailyService = Depends(get_daily_service),
):
    """Create a new workshop. Only trainers may create workshops."""
    user = await session.get(User, user_id)
    if user is None or user.role != UserRole.TRAINER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only trainers can create workshops",
        )

    start_time = body.start_time
    if start_time.tzinfo is not None:
        from datetime import timezone

        start_time = start_time.astimezone(timezone.utc).replace(tzinfo=None)

    workshop = Workshop(
        trainer_id=user_id,
        title=body.title,
        description=body.description,
        start_time=start_time,
        duration_minutes=body.duration_minutes,
        price=body.price,
        max_participants=body.max_participants,
    )
    session.add(workshop)
    await session.commit()
    await session.refresh(workshop)

    # Create Daily.co room for this workshop
    room_name = f"kalba-{workshop.id}"
    try:
        await daily.create_room(
            name=room_name,
            max_participants=workshop.max_participants,
            start_time=workshop.start_time,
            duration_minutes=workshop.duration_minutes,
        )
    except DailyServiceError:
        logger.warning("Failed to create Daily room for workshop %s", workshop.id)
    workshop.video_room_id = room_name
    session.add(workshop)

    # Create default rules
    rules = WorkshopRules(workshop_id=workshop.id)
    session.add(rules)

    await session.commit()
    await session.refresh(workshop)
    return workshop
