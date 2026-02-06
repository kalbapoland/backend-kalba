from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

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

    trainer: User | None = Relationship()
