from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.workshop import WorkshopCreate


def _valid_payload(**overrides) -> dict:
    return {
        "title": "Morning Meditation",
        "description": "A relaxing session",
        "start_time": datetime.now(UTC) + timedelta(days=1),
        "duration_minutes": 60,
        "price": Decimal("10.00"),
        "max_participants": 10,
        **overrides,
    }


# --- start_time validation ---


def test_workshop_create_accepts_future_start_time():
    payload = _valid_payload()
    workshop = WorkshopCreate(**payload)
    assert workshop.title == payload["title"]


def test_workshop_create_rejects_past_start_time():
    with pytest.raises(ValidationError) as exc_info:
        WorkshopCreate(**_valid_payload(start_time=datetime.now(UTC) - timedelta(hours=1)))
    errors = exc_info.value.errors()
    assert any("future" in str(e["msg"]).lower() for e in errors)


def test_workshop_create_rejects_start_time_exactly_now():
    # A datetime equal to "now" is also considered past/not-future.
    with pytest.raises(ValidationError):
        WorkshopCreate(**_valid_payload(start_time=datetime.now(UTC)))


def test_workshop_create_rejects_start_time_yesterday():
    with pytest.raises(ValidationError):
        WorkshopCreate(**_valid_payload(start_time=datetime.now(UTC) - timedelta(days=1)))


def test_workshop_create_rejects_naive_past_datetime():
    """Naive datetimes are treated as UTC — past ones must be rejected."""
    past_naive = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None)
    with pytest.raises(ValidationError):
        WorkshopCreate(**_valid_payload(start_time=past_naive))


def test_workshop_create_accepts_naive_future_datetime():
    """Naive future datetimes (treated as UTC) should be accepted."""
    future_naive = (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None)
    workshop = WorkshopCreate(**_valid_payload(start_time=future_naive))
    assert workshop.title == "Morning Meditation"
