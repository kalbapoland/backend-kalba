from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlmodel import Field, Relationship, SQLModel

from app.models.user import User


class Workshop(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    trainer_id: UUID = Field(foreign_key="user.id", index=True)
    title: str
    description: str = ""
    start_time: datetime
    duration_minutes: int = Field(ge=1)
    price: Decimal = Field(default=Decimal("0.00"), decimal_places=2, max_digits=10)
    max_participants: int = Field(ge=1)
    video_room_id: str | None = Field(default=None)

    trainer: User | None = Relationship()
    rules: Optional["WorkshopRules"] = Relationship(back_populates="workshop")
    participants: list["WorkshopParticipant"] = Relationship()


class WorkshopCreate(BaseModel):
    title: str
    description: str = ""
    start_time: datetime
    duration_minutes: int
    price: Decimal = Decimal("0.00")
    max_participants: int


class WorkshopUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    start_time: datetime | None = None
    duration_minutes: int | None = None
    price: Decimal | None = None
    max_participants: int | None = None


class WorkshopRead(BaseModel):
    id: UUID
    trainer_id: UUID
    title: str
    description: str
    start_time: datetime
    duration_minutes: int
    price: Decimal
    max_participants: int
