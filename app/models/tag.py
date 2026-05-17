from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel


class Tag(SQLModel, table=True):
    """A normalized hashtag (lowercase, NFC unicode) referenced by workshops.

    Created on first use via `services.hashtags.set_workshop_tags`; never
    updated. No deletion path today — orphaned tags stay in the table.
    """

    __tablename__ = "tag"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # `unique=True` produces a UNIQUE constraint backed by an implicit unique
    # index in Postgres — that single index is the source of truth and is what
    # `ON CONFLICT (name) DO NOTHING` resolves against in `upsert_tags`.
    name: str = Field(
        sa_column=Column(String(30), unique=True, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )


class WorkshopTag(SQLModel, table=True):
    __tablename__ = "workshop_tag"

    workshop_id: UUID = Field(
        foreign_key="workshop.id",
        primary_key=True,
        ondelete="CASCADE",
    )
    tag_id: UUID = Field(
        foreign_key="tag.id",
        primary_key=True,
        ondelete="CASCADE",
    )
