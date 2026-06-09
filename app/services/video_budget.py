"""Daily.co participant-minute budget guard.

Daily bills per participant-minute. To guarantee we never cross from the free
tier into paid usage, every issued join token reserves its worst-case minutes
(now -> room expiry) against a rolling-window cap *before* the token exists.
While reservations stand, summed usage can never exceed the cap; once Daily
reports actual usage via webhook, the row is settled to the real minutes,
releasing the unused reservation.

Because we measure over a rolling window at least as long as any monthly
billing cycle, the guarantee holds no matter when Daily's cycle resets.
"""

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.models.video import VideoBudgetStatus, VideoUsageSession
from app.models.workshop import Workshop

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def estimate_session_minutes(
    workshop: Workshop, now: datetime | None = None
) -> int:
    """Worst-case participant-minutes a single join could cost.

    A meeting token only gates *entry*; once joined, a participant can stay
    until the room expires. The room expiry mirrors `DailyService.create_room`
    (workshop end + 10 min grace, never in the past), so the longest this join
    could accrue is from now until that expiry.
    """
    now = now or _utcnow_naive()
    room_exp = max(
        workshop.start_time + timedelta(minutes=workshop.duration_minutes + 10),
        now + timedelta(minutes=10),
    )
    seconds = (room_exp - now).total_seconds()
    return max(1, math.ceil(seconds / 60))


async def current_usage_minutes(
    session: AsyncSession, settings: Settings, now: datetime | None = None
) -> int:
    """Participant-minutes committed in the rolling window.

    Settled rows count their real minutes; outstanding reservations count their
    worst-case minutes. This is the value the cap is enforced against.
    """
    now = now or _utcnow_naive()
    cutoff = now - timedelta(days=settings.daily_usage_window_days)
    counted = case(
        (VideoUsageSession.settled.is_(True), VideoUsageSession.actual_minutes),
        else_=VideoUsageSession.reserved_minutes,
    )
    stmt = select(func.coalesce(func.sum(counted), 0)).where(
        VideoUsageSession.created_at >= cutoff
    )
    return int((await session.exec(stmt)).one())


@dataclass
class ReservationResult:
    allowed: bool
    used_minutes: int
    estimate_minutes: int
    cap_minutes: int
    reservation_id: UUID | None = None
    created_new: bool = False


async def reserve_seat(
    session: AsyncSession,
    settings: Settings,
    workshop: Workshop,
    user_id: UUID,
    now: datetime | None = None,
) -> ReservationResult:
    """Try to reserve budget for a join. Blocks (allowed=False) if over cap.

    A user re-requesting a join for the same workshop refreshes their existing
    outstanding reservation instead of stacking new ones, so reconnects don't
    inflate usage.
    """
    now = now or _utcnow_naive()
    est = estimate_session_minutes(workshop, now)
    cap = settings.daily_minute_budget
    cutoff = now - timedelta(days=settings.daily_usage_window_days)

    existing_stmt = (
        select(VideoUsageSession)
        .where(
            VideoUsageSession.workshop_id == workshop.id,
            VideoUsageSession.user_id == user_id,
            VideoUsageSession.settled.is_(False),
            VideoUsageSession.created_at >= cutoff,
        )
        .order_by(VideoUsageSession.created_at.desc())
    )
    existing = (await session.exec(existing_stmt)).first()

    used = await current_usage_minutes(session, settings, now)
    prior = existing.reserved_minutes if existing else 0
    projected = used - prior + est

    if settings.daily_budget_enforcement_enabled and projected > cap:
        return ReservationResult(
            allowed=False,
            used_minutes=used,
            estimate_minutes=est,
            cap_minutes=cap,
        )

    if existing is not None:
        existing.reserved_minutes = est
        existing.created_at = now  # re-anchor the rolling window
        session.add(existing)
        await session.commit()
        return ReservationResult(
            allowed=True,
            used_minutes=projected,
            estimate_minutes=est,
            cap_minutes=cap,
            reservation_id=existing.id,
            created_new=False,
        )

    reservation = VideoUsageSession(
        workshop_id=workshop.id,
        user_id=user_id,
        reserved_minutes=est,
        created_at=now,
    )
    session.add(reservation)
    await session.commit()
    await session.refresh(reservation)
    return ReservationResult(
        allowed=True,
        used_minutes=projected,
        estimate_minutes=est,
        cap_minutes=cap,
        reservation_id=reservation.id,
        created_new=True,
    )


async def release_reservation(
    session: AsyncSession, reservation_id: UUID
) -> None:
    """Undo a reservation when the join ultimately fails (e.g. Daily errored).

    Only releases still-outstanding reservations so a late webhook settlement
    is never clobbered.
    """
    reservation = await session.get(VideoUsageSession, reservation_id)
    if reservation is not None and not reservation.settled:
        await session.delete(reservation)
        await session.commit()


async def settle_session(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    actual_minutes: int,
    now: datetime | None = None,
) -> bool:
    """Record real minutes for a participant (from a Daily `participant.left`).

    Settles the most recent outstanding reservation for the pair, freeing the
    unused portion of its reservation. Returns False if nothing matched.
    """
    now = now or _utcnow_naive()
    stmt = (
        select(VideoUsageSession)
        .where(
            VideoUsageSession.workshop_id == workshop_id,
            VideoUsageSession.user_id == user_id,
            VideoUsageSession.settled.is_(False),
        )
        .order_by(VideoUsageSession.created_at.desc())
    )
    reservation = (await session.exec(stmt)).first()
    if reservation is None:
        return False

    # Reserved is the worst case, so actual can never legitimately exceed it;
    # clamp defensively to keep the ledger a true upper bound.
    reservation.actual_minutes = max(0, min(actual_minutes, reservation.reserved_minutes))
    reservation.settled = True
    reservation.settled_at = now
    session.add(reservation)
    await session.commit()
    return True


async def budget_status(
    session: AsyncSession, settings: Settings, now: datetime | None = None
) -> VideoBudgetStatus:
    used = await current_usage_minutes(session, settings, now)
    cap = settings.daily_minute_budget
    return VideoBudgetStatus(
        used_minutes=used,
        cap_minutes=cap,
        remaining_minutes=max(0, cap - used),
        window_days=settings.daily_usage_window_days,
        enforced=settings.daily_budget_enforcement_enabled,
    )
