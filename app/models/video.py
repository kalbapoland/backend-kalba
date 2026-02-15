import enum
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlmodel import Field, Relationship, SQLModel


class LateJoinBehavior(str, enum.Enum):
    ALLOW = "allow"
    ALLOW_MUTED = "allow_muted"
    DENY = "deny"


class HostActionType(str, enum.Enum):
    MUTE_ALL = "mute_all"
    UNMUTE_ALL = "unmute_all"
    CAMERAS_OFF_ALL = "cameras_off_all"
    CAMERAS_ON_ALL = "cameras_on_all"


class ParticipantRole(str, enum.Enum):
    HOST = "host"
    PARTICIPANT = "participant"


class WorkshopRules(SQLModel, table=True):
    __tablename__ = "workshop_rules"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workshop_id: UUID = Field(foreign_key="workshop.id", unique=True, index=True)
    force_camera_on: bool = True
    force_mic_muted_on_join: bool = True
    allow_unmute_after: int = Field(default=0)  # seconds; 0 = immediately
    allow_camera_toggle: bool = True
    late_join_behavior: LateJoinBehavior = Field(default=LateJoinBehavior.ALLOW_MUTED)
    all_muted: bool = False
    all_cameras_off: bool = False

    workshop: Optional["Workshop"] = Relationship(back_populates="rules")


class WorkshopParticipant(SQLModel, table=True):
    __tablename__ = "workshop_participant"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    workshop_id: UUID = Field(foreign_key="workshop.id", index=True)
    role: ParticipantRole = Field(default=ParticipantRole.PARTICIPANT)
    joined_at: datetime | None = None


class RulesRead(BaseModel):
    force_camera_on: bool
    force_mic_muted_on_join: bool
    allow_unmute_after: int
    allow_camera_toggle: bool
    all_muted: bool
    all_cameras_off: bool


class JoinResponse(BaseModel):
    token: str
    room_url: str
    role: str  # "host" | "participant"
    rules: RulesRead


class HostAction(BaseModel):
    action: HostActionType
    target_user_id: UUID | None = None


class HostActionResponse(BaseModel):
    status: str
    action: HostActionType
    broadcast_sent: bool
