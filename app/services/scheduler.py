"""Reminder scheduler — DB-polling loop for workshop push notifications.

Runs as a background task started in `app/main.py:lifespan`. Every
`notification_poll_seconds` it scans for workshops whose start_time
falls within their `reminder_minutes_before` window and dispatches a
push notification.

**Phase 1 scope (per `frontend/docs/DESIGN.md` → Push Notifications →
Decisions): the recipient is the *workshop trainer only*.** Participant
reminders are an explicit Phase 2 follow-up; do not silently extend the
recipient set without updating the design doc.

Idempotency / single-shot:
- A due workshop is *atomically claimed* by a single SQL statement that
  sets `reminder_sent_at = now()` only when it is still NULL. This makes
  the claim safe under multiple scheduler instances (Fly multi-machine,
  blue/green overlap) — losers of the race observe 0 affected rows and
  skip.
- We claim *before* dispatching, so a transient Expo failure leaves the
  workshop marked-sent. This is the agreed product trade-off: single
  reminder per workshop, even if delivery partially fails. Failure
  counts surface in `DispatchResult` logs.

The polling-loop choice over APScheduler is also documented in
`frontend/docs/DESIGN.md`.
"""

import asyncio
import logging
from datetime import UTC, datetime
from math import ceil
from uuid import UUID

from sqlalchemy import func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.db import async_session
from app.models.workshop import Workshop
from app.services.my_kalba_notifications import (
    create_workshop_reminder_notifications,
)
from app.services.notifications import (
    DispatchResult,
    PushMessage,
    send_push_to_users,
)

logger = logging.getLogger(__name__)

REMINDER_TITLE = "Your workshop starts soon"


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _minutes_until_start(
    start_time: datetime, *, now: datetime | None = None
) -> int:
    reference_time = now or _utc_now_naive()
    seconds_until_start = (start_time - reference_time).total_seconds()
    return max(1, ceil(seconds_until_start / 60))


def _build_reminder(
    workshop: Workshop, *, now: datetime | None = None
) -> PushMessage:
    minutes_until_start = _minutes_until_start(workshop.start_time, now=now)
    minute_label = "minute" if minutes_until_start == 1 else "minutes"
    body = f'"{workshop.title}" starts in {minutes_until_start} {minute_label}'
    return PushMessage(
        title=REMINDER_TITLE,
        body=body,
        data={"workshop_id": str(workshop.id), "type": "reminder"},
    )


def _build_due_query(now: datetime):
    """SELECT workshops whose start_time is inside the per-row reminder window."""
    return (
        select(Workshop)
        .where(
            Workshop.deleted_at.is_(None),
            Workshop.reminder_sent_at.is_(None),
            Workshop.start_time > now,
            Workshop.start_time
            <= now
            + func.make_interval(0, 0, 0, 0, 0, Workshop.reminder_minutes_before),
        )
        .order_by(Workshop.start_time)
    )


async def _claim_workshop(session: AsyncSession, workshop_id: UUID) -> bool:
    """Atomically mark a workshop as reminded. Return True iff this caller won the race.

    The conditional UPDATE prevents two scheduler instances (or two
    overlapping ticks) from both dispatching the same reminder.
    """
    # Mirror the SELECT predicates as defense-in-depth: a workshop
    # soft-deleted between SELECT and claim must not be dispatched.
    stmt = (
        update(Workshop)
        .where(
            Workshop.id == workshop_id,
            Workshop.reminder_sent_at.is_(None),
            Workshop.deleted_at.is_(None),
        )
        .values(reminder_sent_at=_utc_now_naive())
    )
    result = await session.exec(stmt)
    await session.commit()
    return result.rowcount == 1


async def _dispatch_for_workshop(
    session: AsyncSession, workshop: Workshop
) -> DispatchResult:
    """Send the reminder push for an already-claimed workshop.

    Phase 1: trainer only. Participants are scheduled for Phase 2 — see
    `frontend/docs/DESIGN.md` (Push Notifications → Future improvements).
    """
    message = _build_reminder(workshop)
    result = await send_push_to_users(
        session,
        user_ids=[workshop.trainer_id],
        message=message,
    )
    in_app_created = await create_workshop_reminder_notifications(
        session,
        workshop=workshop,
    )
    await session.commit()
    logger.info(
        "Reminder fired for workshop %s (trainer=%s): sent=%d invalidated=%d failed=%d in_app=%d",
        workshop.id,
        workshop.trainer_id,
        result.sent,
        result.invalidated,
        result.failed,
        in_app_created,
    )
    return result


async def tick(settings: Settings | None = None) -> int:
    """Run a single scheduler iteration. Returns the number of workshops processed.

    Exposed separately from the loop for tests.
    """
    settings = settings or get_settings()

    async with async_session() as session:
        due_rows = await session.exec(_build_due_query(_utc_now_naive()))
        workshop_ids = [w.id for w in due_rows.all()]

    if not workshop_ids:
        return 0

    processed = 0
    for workshop_id in workshop_ids:
        try:
            async with async_session() as session:
                claimed = await _claim_workshop(session, workshop_id)
                if not claimed:
                    # Another scheduler/tick already took this one.
                    continue

                workshop = await session.get(Workshop, workshop_id)
                if workshop is None:
                    continue
                await _dispatch_for_workshop(session, workshop)
                processed += 1
        except Exception:
            # One bad workshop must not stop the rest of the batch.
            # Note: the workshop is already marked sent (claim happened
            # before dispatch) — this preserves single-shot semantics on
            # mid-flight failures, at the cost of a missed delivery.
            logger.exception("Reminder dispatch failed for workshop %s", workshop_id)

    return processed


async def run_reminder_loop(settings: Settings | None = None) -> None:
    """Background task: poll for due reminders forever.

    Cancellation-safe: catches `asyncio.CancelledError` to allow clean
    shutdown via `task.cancel()` in `lifespan`. Per-tick exceptions are
    swallowed so a transient failure (DB blip, Expo outage) does not
    kill the loop.
    """
    settings = settings or get_settings()

    if not settings.notifications_enabled:
        logger.info("Notifications disabled by config; reminder loop not started.")
        return

    logger.info(
        "Reminder loop started (poll every %ds)", settings.notification_poll_seconds
    )

    try:
        while True:
            try:
                processed = await tick(settings)
                if processed:
                    logger.info("Reminder tick processed %d workshop(s)", processed)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Reminder tick failed; continuing")

            await asyncio.sleep(settings.notification_poll_seconds)
    except asyncio.CancelledError:
        logger.info("Reminder loop cancelled; exiting cleanly.")
        raise


def start_reminder_loop_task(
    settings: Settings | None = None,
) -> asyncio.Task[None] | None:
    """Spawn `run_reminder_loop` as a background task or return None when disabled."""
    settings = settings or get_settings()
    if not settings.notifications_enabled:
        logger.info("Notifications disabled by config; reminder task not scheduled.")
        return None
    return asyncio.create_task(run_reminder_loop(settings), name="reminder-loop")
