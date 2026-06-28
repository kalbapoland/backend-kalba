from datetime import UTC, datetime
from math import ceil
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.my_kalba import UserNotification, UserNotificationType
from app.models.workshop import Workshop, WorkshopEnrollment


def _minutes_until_start(start_time: datetime, *, now: datetime | None = None) -> int:
    reference_time = now or datetime.now(UTC).replace(tzinfo=None)
    seconds_until_start = (start_time - reference_time).total_seconds()
    return max(1, ceil(seconds_until_start / 60))


async def create_workshop_rescheduled_notifications(
    session: AsyncSession,
    *,
    workshop: Workshop,
    previous_start_time: datetime,
) -> int:
    enrolled_ids = (
        await session.exec(
            select(WorkshopEnrollment.user_id).where(
                WorkshopEnrollment.workshop_id == workshop.id
            )
        )
    ).all()
    if not enrolled_ids:
        return 0

    notifications = [
        UserNotification(
            user_id=user_id,
            type=UserNotificationType.WORKSHOP_RESCHEDULED,
            title="Workshop schedule updated",
            body=f'"{workshop.title}" has a new start time.',
            payload={
                "workshop_id": str(workshop.id),
                "old_start_time": previous_start_time.isoformat(),
                "new_start_time": workshop.start_time.isoformat(),
            },
        )
        for user_id in enrolled_ids
    ]
    session.add_all(notifications)
    return len(notifications)


async def create_workshop_cancelled_notifications(
    session: AsyncSession,
    *,
    workshop: Workshop,
) -> list[UUID]:
    enrolled_ids = (
        await session.exec(
            select(WorkshopEnrollment.user_id).where(
                WorkshopEnrollment.workshop_id == workshop.id
            )
        )
    ).all()
    if not enrolled_ids:
        return []

    notifications = [
        UserNotification(
            user_id=user_id,
            type=UserNotificationType.WORKSHOP_CANCELLED,
            title="Workshop cancelled",
            body=f'"{workshop.title}" has been cancelled.',
            payload={"workshop_id": str(workshop.id)},
        )
        for user_id in enrolled_ids
    ]
    session.add_all(notifications)
    return list(enrolled_ids)


async def create_workshop_reminder_notifications(
    session: AsyncSession,
    *,
    workshop: Workshop,
    now: datetime | None = None,
) -> int:
    enrolled_ids = (
        await session.exec(
            select(WorkshopEnrollment.user_id).where(
                WorkshopEnrollment.workshop_id == workshop.id
            )
        )
    ).all()
    if not enrolled_ids:
        return 0

    minutes_until_start = _minutes_until_start(workshop.start_time, now=now)
    minute_label = "minute" if minutes_until_start == 1 else "minutes"
    body = f'"{workshop.title}" starts in {minutes_until_start} {minute_label}'

    notifications = [
        UserNotification(
            user_id=user_id,
            type=UserNotificationType.WORKSHOP_REMINDER,
            title="Workshop reminder",
            body=body,
            payload={"workshop_id": str(workshop.id)},
        )
        for user_id in enrolled_ids
    ]
    session.add_all(notifications)
    return len(notifications)
