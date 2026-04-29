import enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel


class UserRole(str, enum.Enum):
    USER = "user"
    TRAINER = "trainer"


class User(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    full_name: str = ""
    is_active: bool = True
    google_id: str | None = Field(default=None, unique=True, index=True)
    hashed_password: str | None = None
    role: UserRole = Field(default=UserRole.USER)

    trainer_profile: Optional["TrainerProfile"] = Relationship(back_populates="user")


class TrainerProfile(SQLModel, table=True):
    __tablename__ = "trainer_profile"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", unique=True, index=True)
    bio: str = ""
    specialties: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False),
    )

    user: User | None = Relationship(back_populates="trainer_profile")


class UserRead(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_active: bool
    role: UserRole
