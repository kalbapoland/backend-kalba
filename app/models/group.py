from datetime import UTC, datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, field_validator
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.user import User


def _utc_now_naive() -> datetime:
    """Store timestamps as UTC-naive for DB consistency (matches Workshop)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Group(SQLModel, table=True):
    # "group" is a reserved SQL keyword; SQLAlchemy auto-quotes the identifier.
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    trainer_id: UUID = Field(foreign_key="user.id", index=True)
    title: str
    description: str = ""
    created_at: datetime = Field(default_factory=_utc_now_naive)
    updated_at: datetime = Field(default_factory=_utc_now_naive)
    deleted_at: datetime | None = Field(default=None, index=True)

    trainer: User | None = Relationship()


class GroupMembership(SQLModel, table=True):
    __tablename__ = "group_membership"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_group_membership_user_group"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    group_id: UUID = Field(foreign_key="group.id", index=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    role: str = Field(default="member")  # "member" | "trainer_subscriber"
    joined_at: datetime = Field(default_factory=_utc_now_naive)


class GroupCreate(BaseModel):
    title: str
    description: str = ""


class GroupUpdate(BaseModel):
    title: str | None = None
    description: str | None = None


class GroupRead(BaseModel):
    id: UUID
    trainer_id: UUID
    title: str
    description: str
    created_at: datetime
    # Caller-context fields set by handlers; defaults keep call sites simple.
    member_count: int = 0
    is_owner: bool = False
    is_member: bool = False

    @field_validator("created_at", mode="before")
    @classmethod
    def ensure_utc_aware(cls, v: datetime) -> datetime:
        """Attach UTC tzinfo to naive datetimes so the API returns 'Z' suffix."""
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class GroupMemberRead(BaseModel):
    id: UUID
    user_id: UUID
    full_name: str
    role: str
