from datetime import UTC, datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, field_validator
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.tag import Tag, WorkshopTag
from app.models.user import User
from app.models.video import WorkshopRules, WorkshopParticipant


class Workshop(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    trainer_id: UUID = Field(foreign_key="user.id", index=True)
    group_id: UUID = Field(foreign_key="group.id", index=True)
    title: str
    description: str = ""
    start_time: datetime
    duration_minutes: int = Field(ge=1)
    timezone: str = Field(default="UTC")  # IANA timezone, e.g. "America/Los_Angeles"
    price: Decimal = Field(default=Decimal("0.00"), decimal_places=2, max_digits=10)
    max_participants: int = Field(ge=1)
    video_room_id: str | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None, index=True)
    reminder_minutes_before: int = Field(default=60, ge=1)
    reminder_sent_at: datetime | None = Field(default=None, index=True)

    trainer: User | None = Relationship()
    rules: Optional["WorkshopRules"] = Relationship(back_populates="workshop")
    participants: list["WorkshopParticipant"] = Relationship()
    tags: list["Tag"] = Relationship(link_model=WorkshopTag)


class WorkshopEnrollment(SQLModel, table=True):
    __tablename__ = "workshop_enrollment"
    __table_args__ = (
        UniqueConstraint("user_id", "workshop_id", name="uq_workshop_enrollment_user_workshop"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    workshop_id: UUID = Field(foreign_key="workshop.id", index=True)
    enrolled_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class WorkshopCreate(BaseModel):
    title: str
    description: str = ""
    start_time: datetime
    duration_minutes: int
    timezone: str = "UTC"  # IANA timezone where the event was created
    price: Decimal = Decimal("0.00")
    max_participants: int
    group_id: UUID  # workshops must belong to a group the trainer owns
    reminder_minutes_before: int | None = None  # None → use server default

    @field_validator("reminder_minutes_before")
    @classmethod
    def validate_reminder_minutes(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("reminder_minutes_before must be >= 1")
        return v

    @field_validator("start_time")
    @classmethod
    def validate_start_time_not_in_past(cls, v: datetime) -> datetime:
        now_utc = datetime.now(timezone.utc)
        candidate = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        if candidate <= now_utc:
            raise ValueError("Workshop start_time must be in the future")
        return v


class WorkshopUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    start_time: datetime | None = None
    duration_minutes: int | None = None
    timezone: str | None = None
    price: Decimal | None = None
    max_participants: int | None = None
    reminder_minutes_before: int | None = None

    @field_validator("reminder_minutes_before")
    @classmethod
    def validate_reminder_minutes(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("reminder_minutes_before must be >= 1")
        return v

    @field_validator("start_time")
    @classmethod
    def validate_start_time_not_in_past(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        now_utc = datetime.now(timezone.utc)
        candidate = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        if candidate <= now_utc:
            raise ValueError("Workshop start_time must be in the future")
        return v


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
    group_id: UUID
    reminder_minutes_before: int
    tags: list[str] = []
    # Caller-context fields set by handlers; defaults keep existing call sites working.
    is_owner: bool = False
    is_enrolled: bool = False
    enrolled_count: int = 0

    @field_validator("start_time", mode="before")
    @classmethod
    def ensure_utc_aware(cls, v: datetime) -> datetime:
        """Attach UTC tzinfo to naive datetimes so the API returns 'Z' suffix."""
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def coerce_tags(cls, v) -> list[str]:
        """Accept a list of Tag rows or strings; emit plain names."""
        if v is None:
            return []
        return [t.name if isinstance(t, Tag) else t for t in v]
