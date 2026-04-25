"""End-to-end tests for the reminder scheduler tick.

Uses real Postgres (via the integration conftest) and a stub
`send_push_to_users` so the scheduler is exercised in isolation from
the dispatch service.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.workshop import Workshop
from app.services import scheduler
from app.services.notifications import DispatchResult, PushMessage


# --- Helpers ---


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _create_workshop(
    session,
    trainer,
    *,
    minutes_until_start: float,
    reminder_minutes: int = 60,
    reminder_sent_at: datetime | None = None,
    deleted: bool = False,
    title: str = "Test Workshop",
) -> Workshop:
    workshop = Workshop(
        trainer_id=trainer.id,
        title=title,
        description="",
        start_time=_now_naive() + timedelta(minutes=minutes_until_start),
        duration_minutes=60,
        timezone="UTC",
        max_participants=10,
        reminder_minutes_before=reminder_minutes,
        reminder_sent_at=reminder_sent_at,
        deleted_at=_now_naive() if deleted else None,
    )
    session.add(workshop)
    await session.commit()
    await session.refresh(workshop)
    return workshop


@pytest.fixture
def stub_dispatch(monkeypatch):
    """Replace send_push_to_users so the scheduler tests don't make HTTP calls."""
    calls: list[dict] = []

    async def fake_send(session, *, user_ids, message: PushMessage, **_kw):
        calls.append(
            {
                "user_ids": list(user_ids),
                "title": message.title,
                "body": message.body,
                "data": message.data,
            }
        )
        return DispatchResult(sent=len(user_ids), invalidated=0, failed=0)

    monkeypatch.setattr(scheduler, "send_push_to_users", fake_send)
    return calls


# --- tick() behaviour ---


async def test_tick_fires_due_workshop(db_session, trainer, stub_dispatch):
    """Workshop within window → dispatch called, reminder_sent_at set."""
    workshop = await _create_workshop(
        db_session, trainer, minutes_until_start=30, reminder_minutes=60
    )

    processed = await scheduler.tick()

    assert processed == 1
    assert len(stub_dispatch) == 1
    assert stub_dispatch[0]["user_ids"] == [trainer.id]
    assert stub_dispatch[0]["data"] == {
        "workshop_id": str(workshop.id),
        "type": "reminder",
    }

    refreshed = await db_session.get(Workshop, workshop.id)
    await db_session.refresh(refreshed)
    assert refreshed.reminder_sent_at is not None


async def test_tick_skips_out_of_window_workshop(db_session, trainer, stub_dispatch):
    """Workshop starts in 5h with 60-min lead → not yet due."""
    await _create_workshop(
        db_session, trainer, minutes_until_start=300, reminder_minutes=60
    )

    processed = await scheduler.tick()

    assert processed == 0
    assert stub_dispatch == []


async def test_tick_skips_already_sent_workshop(db_session, trainer, stub_dispatch):
    """Workshop with reminder_sent_at set → idempotent skip."""
    await _create_workshop(
        db_session,
        trainer,
        minutes_until_start=30,
        reminder_minutes=60,
        reminder_sent_at=_now_naive(),
    )

    processed = await scheduler.tick()

    assert processed == 0
    assert stub_dispatch == []


async def test_tick_skips_soft_deleted_workshop(db_session, trainer, stub_dispatch):
    """deleted_at != NULL → never reminded."""
    await _create_workshop(
        db_session, trainer, minutes_until_start=30, reminder_minutes=60, deleted=True
    )

    processed = await scheduler.tick()

    assert processed == 0
    assert stub_dispatch == []


async def test_tick_skips_already_started_workshop(db_session, trainer, stub_dispatch):
    """start_time in the past → window has closed; skip."""
    await _create_workshop(
        db_session, trainer, minutes_until_start=-5, reminder_minutes=60
    )

    processed = await scheduler.tick()

    assert processed == 0
    assert stub_dispatch == []


async def test_tick_processes_multiple_due_workshops(
    db_session, trainer, stub_dispatch
):
    await _create_workshop(
        db_session, trainer, minutes_until_start=10, reminder_minutes=60, title="A"
    )
    await _create_workshop(
        db_session, trainer, minutes_until_start=20, reminder_minutes=60, title="B"
    )

    processed = await scheduler.tick()

    assert processed == 2
    titles_in_dispatched_bodies = sorted(c["body"] for c in stub_dispatch)
    assert titles_in_dispatched_bodies[0].startswith('"A"')
    assert titles_in_dispatched_bodies[1].startswith('"B"')


async def test_tick_marks_sent_even_when_dispatch_returns_zero(
    db_session, trainer, monkeypatch
):
    """Single-shot semantics: reminder_sent_at advances even when no tokens deliver."""
    workshop = await _create_workshop(
        db_session, trainer, minutes_until_start=10, reminder_minutes=60
    )

    async def all_failed(session, *, user_ids, message, **_kw):
        return DispatchResult(sent=0, invalidated=0, failed=1)

    monkeypatch.setattr(scheduler, "send_push_to_users", all_failed)

    processed = await scheduler.tick()

    assert processed == 1
    refreshed = await db_session.get(Workshop, workshop.id)
    await db_session.refresh(refreshed)
    assert refreshed.reminder_sent_at is not None


async def test_tick_one_failure_does_not_block_other_workshops(
    db_session, trainer, monkeypatch
):
    """An exception on one dispatch must not prevent later workshops from firing.

    Note: with claim-then-dispatch ordering, the failing workshop is
    still *marked* sent (the claim succeeded before the dispatch raised),
    so it is not re-tried — single-shot semantics preserve at-most-once.
    """
    bad = await _create_workshop(
        db_session, trainer, minutes_until_start=10, reminder_minutes=60, title="Bad"
    )
    good = await _create_workshop(
        db_session, trainer, minutes_until_start=20, reminder_minutes=60, title="Good"
    )

    async def selective_send(session, *, user_ids, message, **_kw):
        if "Bad" in message.body:
            raise RuntimeError("simulated upstream failure")
        return DispatchResult(sent=1, invalidated=0, failed=0)

    monkeypatch.setattr(scheduler, "send_push_to_users", selective_send)

    processed = await scheduler.tick()

    # "Good" succeeds; "Bad"'s exception is swallowed so the loop continues.
    assert processed == 1

    bad_after = await db_session.get(Workshop, bad.id)
    good_after = await db_session.get(Workshop, good.id)
    await db_session.refresh(bad_after)
    await db_session.refresh(good_after)
    # Both are claimed (single-shot semantics) — "Bad" lost its delivery
    # but won't be re-fired and the trainer won't get duplicate pushes.
    assert bad_after.reminder_sent_at is not None
    assert good_after.reminder_sent_at is not None


async def test_tick_returns_zero_when_no_workshops(db_session, stub_dispatch):
    processed = await scheduler.tick()
    assert processed == 0
    assert stub_dispatch == []


# --- Atomic claim ---


async def test_claim_workshop_returns_true_only_for_first_caller(
    db_session, trainer
):
    """Concurrent ticks must not both dispatch the same reminder."""
    workshop = await _create_workshop(
        db_session, trainer, minutes_until_start=10, reminder_minutes=60
    )

    from app.db import async_session as app_async_session
    from app.services.scheduler import _claim_workshop

    async with app_async_session() as s1:
        first = await _claim_workshop(s1, workshop.id)
    async with app_async_session() as s2:
        second = await _claim_workshop(s2, workshop.id)

    assert first is True
    assert second is False

    refreshed = await db_session.get(Workshop, workshop.id)
    await db_session.refresh(refreshed)
    assert refreshed.reminder_sent_at is not None
