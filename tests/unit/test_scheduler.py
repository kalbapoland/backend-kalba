"""Pure-unit tests for the reminder scheduler.

End-to-end tick behaviour is covered in
`tests/integration/test_scheduler.py` (requires Postgres).
"""

import asyncio
from datetime import datetime
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.models.workshop import Workshop
from app.services import scheduler
from app.services.scheduler import (
    REMINDER_TITLE,
    _build_reminder,
    run_reminder_loop,
    start_reminder_loop_task,
)


def _isolated_settings(**overrides) -> Settings:
    """Build a Settings instance that ignores `.env.local` (test hermetic)."""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def _make_workshop(*, title: str = "Yoga", lead: int = 60) -> Workshop:
    return Workshop(
        id=uuid4(),
        trainer_id=uuid4(),
        title=title,
        description="",
        start_time=datetime(2026, 5, 1, 10, 0, 0),
        duration_minutes=60,
        timezone="UTC",
        max_participants=10,
        reminder_minutes_before=lead,
    )


def test_build_reminder_payload_shape() -> None:
    workshop = _make_workshop(title="Morning Flow", lead=30)
    msg = _build_reminder(workshop)

    assert msg.title == REMINDER_TITLE
    assert msg.body == '"Morning Flow" starts in 30 min'
    assert msg.data == {
        "workshop_id": str(workshop.id),
        "type": "reminder",
    }


def test_build_reminder_includes_workshop_id_in_data() -> None:
    workshop = _make_workshop()
    msg = _build_reminder(workshop)
    assert msg.data["workshop_id"] == str(workshop.id)


def test_build_reminder_quotes_title_with_special_chars() -> None:
    """Title is interpolated raw — make sure odd characters don't break the body string."""
    workshop = _make_workshop(title='He said "hi"', lead=15)
    msg = _build_reminder(workshop)
    assert 'He said "hi"' in msg.body
    assert msg.body.endswith("in 15 min")


# --- Kill-switch ---


async def test_run_reminder_loop_returns_immediately_when_disabled() -> None:
    settings = _isolated_settings(notifications_enabled=False)
    # Should return immediately (not start the polling loop).
    await asyncio.wait_for(run_reminder_loop(settings), timeout=1.0)


def test_start_reminder_loop_task_returns_none_when_disabled() -> None:
    settings = _isolated_settings(notifications_enabled=False)
    task = start_reminder_loop_task(settings)
    assert task is None


# --- Per-tick exception isolation ---


async def test_loop_swallows_tick_exceptions(monkeypatch) -> None:
    """A throwing tick must not kill the loop; next sleep is still scheduled."""
    calls = {"n": 0}
    sleep_calls = {"n": 0}

    async def boom(_settings):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        # Third call: cancel the loop from inside so the test terminates.
        raise asyncio.CancelledError()

    async def fake_sleep(_seconds):
        sleep_calls["n"] += 1

    monkeypatch.setattr(scheduler, "tick", boom)
    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)

    settings = _isolated_settings(
        notifications_enabled=True, notification_poll_seconds=0
    )

    with pytest.raises(asyncio.CancelledError):
        await run_reminder_loop(settings)

    # Two non-cancel exceptions should have triggered two `await asyncio.sleep` calls
    # (the third raise was CancelledError which short-circuits before the sleep).
    assert calls["n"] == 3
    assert sleep_calls["n"] == 2
