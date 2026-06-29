from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import ErrorCode
from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.my_kalba import (
    MyKalbaDashboardRead,
    MyKalbaStatsRead,
    NotificationReadUpdate,
    UserGoal,
    UserGoalRead,
    UserGoalUpdate,
    UserNotification,
    UserNotificationRead,
)
from app.models.workshop import Workshop, WorkshopEnrollment, WorkshopRead

router = APIRouter(prefix="/users/me/my-kalba", tags=["my-kalba"])


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _get_or_create_goal(session: AsyncSession, user_id: UUID) -> UserGoal:
    now = _utc_now_naive()
    stmt = (
        pg_insert(UserGoal)
        .values(
            user_id=user_id,
            monthly_target=4,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    await session.exec(stmt)
    await session.commit()
    goal = (
        await session.exec(select(UserGoal).where(UserGoal.user_id == user_id))
    ).one()
    return goal


async def _load_upcoming_workshops(
    session: AsyncSession,
    *,
    user_id: UUID,
    now: datetime,
    limit: int = 12,
) -> list[WorkshopRead]:
    enrollment_stmt = select(WorkshopEnrollment.workshop_id).where(
        WorkshopEnrollment.user_id == user_id
    )
    stmt = (
        select(Workshop)
        .where(
            Workshop.id.in_(enrollment_stmt),
            Workshop.deleted_at.is_(None),
            Workshop.start_time >= now,
        )
        .options(selectinload(Workshop.tags))
        .order_by(Workshop.start_time)
        .limit(limit)
    )
    workshops = (await session.exec(stmt)).all()
    if not workshops:
        return []

    workshop_ids = [w.id for w in workshops]
    count_stmt = (
        select(WorkshopEnrollment.workshop_id, func.count(WorkshopEnrollment.id))
        .where(WorkshopEnrollment.workshop_id.in_(workshop_ids))
        .group_by(WorkshopEnrollment.workshop_id)
    )
    counts = {row[0]: row[1] for row in (await session.exec(count_stmt)).all()}

    result: list[WorkshopRead] = []
    for workshop in workshops:
        read = WorkshopRead.model_validate(workshop, from_attributes=True)
        read.is_owner = workshop.trainer_id == user_id
        read.is_enrolled = True
        read.enrolled_count = counts.get(workshop.id, 0)
        result.append(read)
    return result


async def _load_stats(
    session: AsyncSession,
    *,
    user_id: UUID,
    monthly_target: int,
    now: datetime,
) -> MyKalbaStatsRead:
    weekday_index = now.weekday()
    week_start = (now - timedelta(days=weekday_index)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    workshop_end_expr = Workshop.start_time + func.make_interval(
        0, 0, 0, 0, 0, Workshop.duration_minutes
    )
    counts_stmt = (
        select(
            func.count(
                case((workshop_end_expr >= week_start, 1))
            ).label("week_count"),
            func.count(
                case((workshop_end_expr >= month_start, 1))
            ).label("month_count"),
        )
        .select_from(WorkshopEnrollment)
        .join(Workshop, Workshop.id == WorkshopEnrollment.workshop_id)
        .where(
            WorkshopEnrollment.user_id == user_id,
            Workshop.deleted_at.is_(None),
            workshop_end_expr <= now,
        )
    )
    row = (await session.exec(counts_stmt)).one()
    completed_this_week = int(row[0] or 0)
    completed_this_month = int(row[1] or 0)

    progress = 0
    if monthly_target > 0:
        progress = min(100, round((completed_this_month / monthly_target) * 100))

    return MyKalbaStatsRead(
        completed_this_week=completed_this_week,
        completed_this_month=completed_this_month,
        monthly_target=monthly_target,
        monthly_progress_percent=progress,
    )


@router.get("/dashboard", response_model=MyKalbaDashboardRead)
async def get_dashboard(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    now = _utc_now_naive()
    goal = await _get_or_create_goal(session, user_id)
    stats = await _load_stats(
        session,
        user_id=user_id,
        monthly_target=goal.monthly_target,
        now=now,
    )

    unread_stmt = select(func.count(UserNotification.id)).where(
        UserNotification.user_id == user_id,
        UserNotification.deleted_at.is_(None),
        UserNotification.is_read.is_(False),
    )
    unread_count = int((await session.exec(unread_stmt)).one())

    return MyKalbaDashboardRead(
        goal=UserGoalRead(
            user_id=goal.user_id,
            monthly_target=goal.monthly_target,
            updated_at=goal.updated_at,
        ),
        stats=stats,
        unread_notifications=unread_count,
    )


@router.get("/goal", response_model=UserGoalRead)
async def get_goal(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    goal = await _get_or_create_goal(session, user_id)
    return UserGoalRead(
        user_id=goal.user_id,
        monthly_target=goal.monthly_target,
        updated_at=goal.updated_at,
    )


@router.put("/goal", response_model=UserGoalRead)
async def update_goal(
    body: UserGoalUpdate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    goal = await _get_or_create_goal(session, user_id)
    goal.monthly_target = body.monthly_target
    goal.updated_at = _utc_now_naive()
    session.add(goal)
    await session.commit()
    await session.refresh(goal)
    return UserGoalRead(
        user_id=goal.user_id,
        monthly_target=goal.monthly_target,
        updated_at=goal.updated_at,
    )


@router.get("/schedule", response_model=list[WorkshopRead])
async def get_schedule(
    limit: int = Query(default=12, ge=1, le=100),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    return await _load_upcoming_workshops(
        session,
        user_id=user_id,
        now=_utc_now_naive(),
        limit=limit,
    )


@router.get("/notifications", response_model=list[UserNotificationRead])
async def list_notifications(
    unread_only: bool = Query(default=False),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    filters = [
        UserNotification.user_id == user_id,
        UserNotification.deleted_at.is_(None),
    ]
    if unread_only:
        filters.append(UserNotification.is_read.is_(False))

    stmt = (
        select(UserNotification)
        .where(and_(*filters))
        .order_by(UserNotification.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = (await session.exec(stmt)).all()
    return [
        UserNotificationRead(
            id=row.id,
            type=row.type,
            title=row.title,
            body=row.body,
            payload=row.payload,
            is_read=row.is_read,
            read_at=row.read_at,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.patch("/notifications/{notification_id}/read", response_model=UserNotificationRead)
async def update_notification_read_state(
    notification_id: UUID,
    body: NotificationReadUpdate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    notification = await session.get(UserNotification, notification_id)
    if notification is None or notification.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ErrorCode.NOTIFICATION_NOT_FOUND)
    if notification.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ErrorCode.FORBIDDEN)

    notification.is_read = body.is_read
    notification.read_at = _utc_now_naive() if body.is_read else None
    session.add(notification)
    await session.commit()
    await session.refresh(notification)
    return UserNotificationRead(
        id=notification.id,
        type=notification.type,
        title=notification.title,
        body=notification.body,
        payload=notification.payload,
        is_read=notification.is_read,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


@router.post("/notifications/mark-all-read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    now = _utc_now_naive()
    rows = (
        await session.exec(
            select(UserNotification).where(
                UserNotification.user_id == user_id,
                UserNotification.deleted_at.is_(None),
                UserNotification.is_read.is_(False),
            )
        )
    ).all()
    for row in rows:
        row.is_read = True
        row.read_at = now
        session.add(row)
    await session.commit()


@router.delete("/notifications/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    notification = await session.get(UserNotification, notification_id)
    if notification is None or notification.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ErrorCode.NOTIFICATION_NOT_FOUND)
    if notification.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ErrorCode.FORBIDDEN)

    notification.deleted_at = _utc_now_naive()
    session.add(notification)
    await session.commit()
