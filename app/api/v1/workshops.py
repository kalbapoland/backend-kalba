import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.user import User, UserRole
from app.models.video import WorkshopRules
from app.models.workshop import Workshop, WorkshopCreate, WorkshopRead, WorkshopUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workshops", tags=["workshops"])


@router.get("/", response_model=list[WorkshopRead])
async def list_workshops(
    session: AsyncSession = Depends(get_db_session),
):
    """List upcoming and ongoing workshops."""
    now = datetime.now(UTC).replace(tzinfo=None)
    statement = select(Workshop).where(
        text("start_time + (duration_minutes * INTERVAL '1 minute') > :now").bindparams(now=now),
        Workshop.deleted_at.is_(None),
    )
    result = await session.exec(statement)
    rows = result.all()
    logger.info("Returning %d upcoming/ongoing workshops", len(rows))
    return rows


@router.get("/{workshop_id}", response_model=WorkshopRead)
async def get_workshop(
    workshop_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a single workshop by ID."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None or workshop.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Workshop not found")
    logger.info("Workshop %s retrieved", workshop_id)
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
    logger.info(
        "Workshop created: id=%s title=%r start_time=%s trainer=%s",
        workshop.id,
        workshop.title,
        workshop.start_time.isoformat(),
        user_id,
    )
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
    logger.info(
        "Workshop %s updated; fields changed: %s",
        workshop_id,
        ",".join(update_data.keys()) if update_data else "none",
    )
    return workshop


@router.delete("/{workshop_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workshop(
    workshop_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
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

    logger.info("Soft-deleting workshop %s (requested by %s)", workshop_id, user_id)

    workshop.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(workshop)
    await session.commit()
    logger.info("Workshop %s soft-deleted", workshop_id)
