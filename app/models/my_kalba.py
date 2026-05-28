import enum
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import Column
from sqlmodel import Field, SQLModel


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class UserGoal(SQLModel, table=True):
    __tablename__ = "user_goal"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True, unique=True)
    monthly_target: int = Field(default=4, ge=1, le=60)
    created_at: datetime = Field(default_factory=_utc_now_naive)
    updated_at: datetime = Field(default_factory=_utc_now_naive)


class UserNotificationType(str, enum.Enum):
    WORKSHOP_RESCHEDULED = "workshop_rescheduled"
    WORKSHOP_REMINDER = "workshop_reminder"


USER_NOTIFICATION_TYPE_ENUM = sa.Enum(
    UserNotificationType,
    name="usernotificationtype",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class UserNotification(SQLModel, table=True):
    __tablename__ = "user_notification"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    type: UserNotificationType = Field(
        sa_column=Column(USER_NOTIFICATION_TYPE_ENUM, nullable=False)
    )
    title: str
    body: str
    payload: dict[str, str] = Field(default_factory=dict, sa_column=Column(sa.JSON()))
    is_read: bool = Field(default=False, index=True)
    read_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utc_now_naive, index=True)
    deleted_at: datetime | None = Field(default=None, index=True)


class UserGoalRead(BaseModel):
    user_id: UUID
    monthly_target: int
    updated_at: datetime


class UserGoalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_target: int = PydanticField(ge=1, le=60)


class MyKalbaStatsRead(BaseModel):
    completed_this_week: int
    completed_this_month: int
    monthly_target: int
    monthly_progress_percent: int


class UserNotificationRead(BaseModel):
    id: UUID
    type: UserNotificationType
    title: str
    body: str
    payload: dict[str, str]
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class NotificationReadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_read: bool


class MyKalbaDashboardRead(BaseModel):
    goal: UserGoalRead
    stats: MyKalbaStatsRead
    unread_notifications: int
