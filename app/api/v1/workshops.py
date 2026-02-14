import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.user import User, UserRole
from app.models.video import WorkshopParticipant, WorkshopRules
from app.models.workshop import Workshop, WorkshopCreate, WorkshopRead, WorkshopUpdate
from app.services.daily import DailyService, get_daily_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workshops", tags=["workshops"])


@router.get("/", response_model=list[WorkshopRead])
async def list_workshops(
    session: AsyncSession = Depends(get_db_session),
):
    """List all upcoming workshops."""
    statement = select(Workshop).where(
        Workshop.start_time >= datetime.now(UTC).replace(tzinfo=None)
    )
    result = await session.exec(statement)
    return result.all()


@router.get("/{workshop_id}", response_model=WorkshopRead)
async def get_workshop(
    workshop_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a single workshop by ID."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None:
        raise HTTPException(status_code=404, detail="Workshop not found")
    return workshop


@router.post("/", response_model=WorkshopRead, status_code=status.HTTP_201_CREATED)
async def create_workshop(
    body: WorkshopCreate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new workshop. Only trainers may create workshops.

    The Daily.co video room is created lazily when the first person joins.
    """
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
        video_room_id=None,
    )
    session.add(workshop)
    await session.flush()

    # Create default rules
    rules = WorkshopRules(workshop_id=workshop.id)
    session.add(rules)

    await session.commit()
    await session.refresh(workshop)
    return workshop


@router.patch("/{workshop_id}", response_model=WorkshopRead)
async def update_workshop(
    workshop_id: UUID,
    body: WorkshopUpdate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Update a workshop. Only the trainer who created it may edit it."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None:
        raise HTTPException(status_code=404, detail="Workshop not found")

    if workshop.trainer_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workshop creator can edit this workshop",
        )

    update_data = body.model_dump(exclude_unset=True)

    if "start_time" in update_data and update_data["start_time"] is not None:
        from datetime import timezone

        st = update_data["start_time"]
        if st.tzinfo is not None:
            update_data["start_time"] = st.astimezone(timezone.utc).replace(tzinfo=None)

    for field, value in update_data.items():
        setattr(workshop, field, value)

    session.add(workshop)
    await session.commit()
    await session.refresh(workshop)
    return workshop


@router.delete("/{workshop_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workshop(
    workshop_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    daily: DailyService = Depends(get_daily_service),
):
    """Delete a workshop. Only the trainer who created it may delete it."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None:
        raise HTTPException(status_code=404, detail="Workshop not found")

    if workshop.trainer_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workshop creator can delete this workshop",
        )

    # Clean up Daily.co room if one was created
    if workshop.video_room_id:
        await daily.delete_room(workshop.video_room_id)

    # Delete related rows
    participants = await session.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.workshop_id == workshop_id
        )
    )
    for p in participants.all():
        await session.delete(p)

    rules = await session.exec(
        select(WorkshopRules).where(WorkshopRules.workshop_id == workshop_id)
    )
    for r in rules.all():
        await session.delete(r)

    await session.delete(workshop)
    await session.commit()
