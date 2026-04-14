from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, field_validator
from sqlmodel import Field, Relationship, SQLModel

from app.models.user import User
from app.models.video import WorkshopRules, WorkshopParticipant


class Workshop(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    trainer_id: UUID = Field(foreign_key="user.id", index=True)
    title: str
    description: str = ""
    start_time: datetime
    duration_minutes: int = Field(ge=1)
    timezone: str = Field(default="UTC")  # IANA timezone, e.g. "America/Los_Angeles"
    price: Decimal = Field(default=Decimal("0.00"), decimal_places=2, max_digits=10)
    max_participants: int = Field(ge=1)
    video_room_id: str | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None, index=True)

    trainer: User | None = Relationship()
    rules: Optional["WorkshopRules"] = Relationship(back_populates="workshop")
    participants: list["WorkshopParticipant"] = Relationship()


class WorkshopCreate(BaseModel):
    title: str
    description: str = ""
    start_time: datetime
    duration_minutes: int
    timezone: str = "UTC"  # IANA timezone where the event was created
    price: Decimal = Decimal("0.00")
    max_participants: int

    @field_validator("start_time")
    @classmethod
    def start_time_must_be_future(cls, v: datetime) -> datetime:
        """Reject workshops scheduled in the past."""
        now = datetime.now(timezone.utc)
        # Normalise naive datetimes (stored as UTC) for comparison.
        v_aware = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        if v_aware <= now:
            raise ValueError("start_time must be in the future")
        return v


class WorkshopUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    start_time: datetime | None = None
    duration_minutes: int | None = None
    timezone: str | None = None
    price: Decimal | None = None
    max_participants: int | None = None


class WorkshopRead(BaseModel):
    id: UUID
    trainer_id: UUID
    title: str
    description: str
    start_time: datetime
    duration_minutes: int
    timezone: str
    price: Decimal
    max_participants: int

    @field_validator("start_time", mode="before")
    @classmethod
    def ensure_utc_aware(cls, v: datetime) -> datetime:
        """Attach UTC tzinfo to naive datetimes so the API returns 'Z' suffix."""
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
