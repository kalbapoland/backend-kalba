import logging
from datetime import UTC, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.user import User, UserRole
from app.models.video import WorkshopRules
from app.models.workshop import Workshop, WorkshopCreate, WorkshopRead, WorkshopUpdate
from app.services.daily import DailyService, DailyServiceError, get_daily_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workshops", tags=["workshops"])
MIN_WORKSHOP_YEAR = 2024
MAX_WORKSHOP_YEAR = 2100


def normalize_to_utc_naive(dt: datetime) -> datetime:
    """Store workshop start_time as UTC-naive for DB consistency."""
    if dt.tzinfo is None:
        normalized = dt.replace(tzinfo=timezone.utc)
    else:
        normalized = dt.astimezone(timezone.utc)

    if not MIN_WORKSHOP_YEAR <= normalized.year <= MAX_WORKSHOP_YEAR:
        raise ValueError(
            f"Workshop year must be between {MIN_WORKSHOP_YEAR} and {MAX_WORKSHOP_YEAR}"
        )

    return normalized.replace(tzinfo=None)


@router.get("/", response_model=list[WorkshopRead])
async def list_workshops(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    """List all upcoming workshops."""
    now = datetime.now(UTC).replace(tzinfo=None)
    statement = (
        select(Workshop)
        .where(
            Workshop.deleted_at.is_(None),
            Workshop.start_time
            + func.make_interval(0, 0, 0, 0, 0, Workshop.duration_minutes)
            >= now,
        )
        .order_by(Workshop.start_time)
        .offset(skip)
        .limit(limit)
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

    try:
        start_time = normalize_to_utc_naive(body.start_time)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    settings = get_settings()
    reminder_minutes = (
        body.reminder_minutes_before
        if body.reminder_minutes_before is not None
        else settings.notification_lead_minutes_default
    )

    workshop = Workshop(
        trainer_id=user_id,
        title=body.title,
        description=body.description,
        start_time=start_time,
        duration_minutes=body.duration_minutes,
        price=body.price,
        max_participants=body.max_participants,
        timezone=body.timezone,
        video_room_id=None,
        reminder_minutes_before=reminder_minutes,
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
    if workshop is None or workshop.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Workshop not found")

    if workshop.trainer_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workshop creator can edit this workshop",
        )

    update_data = body.model_dump(exclude_unset=True)

    if "start_time" in update_data and update_data["start_time"] is not None:
        st = update_data["start_time"]
        try:
            update_data["start_time"] = normalize_to_utc_naive(st)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Re-arm the reminder if the schedule moves or the lead time changes —
    # the previous "sent" marker no longer reflects user intent.
    rearm_reminder = (
        ("start_time" in update_data and update_data["start_time"] != workshop.start_time)
        or (
            "reminder_minutes_before" in update_data
            and update_data["reminder_minutes_before"] is not None
            and update_data["reminder_minutes_before"] != workshop.reminder_minutes_before
        )
    )

    for field, value in update_data.items():
        setattr(workshop, field, value)

    if (
        rearm_reminder
        and workshop.reminder_sent_at is not None
        and workshop.deleted_at is None
    ):
        workshop.reminder_sent_at = None

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
    daily: DailyService = Depends(get_daily_service),
):
    """Delete a workshop. Only the trainer who created it may delete it."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None or workshop.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Workshop not found")

    if workshop.trainer_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workshop creator can delete this workshop",
        )

    logger.info("Soft-deleting workshop %s (requested by %s)", workshop_id, user_id)

    # Clean up Daily.co room if one was created
    if workshop.video_room_id:
        try:
            await daily.delete_room(workshop.video_room_id)
        except DailyServiceError as exc:
            logger.error(
                "Failed to delete Daily room for workshop %s: %s",
                workshop_id,
                exc.detail,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Video service unavailable",
            ) from exc

    workshop.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(workshop)
    await session.commit()
    logger.info("Workshop %s soft-deleted", workshop_id)
