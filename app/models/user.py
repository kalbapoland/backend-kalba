import enum
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel


class UserRole(str, enum.Enum):
    USER = "user"
    TRAINER = "trainer"


class User(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    full_name: str = ""
    is_active: bool = True
    google_id: str = Field(unique=True, index=True)
    role: UserRole = Field(default=UserRole.USER)

    trainer_profile: Optional["TrainerProfile"] = Relationship(back_populates="user")


class TrainerProfile(SQLModel, table=True):
    __tablename__ = "trainer_profile"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", unique=True, index=True)
    bio: str = ""
    specialties: str = (
        ""  # comma-separated for simplicity; migrate to JSON/array later if needed
    )

    user: User | None = Relationship(back_populates="trainer_profile")
