"""add tag and workshop_tag tables

Revision ID: a3f7d24c8e91
Revises: 3b9e2c1d4f50
Create Date: 2026-05-17 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3f7d24c8e91"
down_revision: Union[str, None] = "3b9e2c1d4f50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "tag" not in existing_tables:
        op.create_table(
            "tag",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=30), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )

    if "workshop_tag" not in existing_tables:
        op.create_table(
            "workshop_tag",
            sa.Column("workshop_id", sa.Uuid(), nullable=False),
            sa.Column("tag_id", sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint(
                ["workshop_id"],
                ["workshop.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tag_id"],
                ["tag.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("workshop_id", "tag_id"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "workshop_tag" in existing_tables:
        op.drop_table("workshop_tag")

    if "tag" in existing_tables:
        op.drop_table("tag")
