"""add workshop_enrollment table

Revision ID: c5e8f1a3d7b2
Revises: b7c1e9fa20d4
Create Date: 2026-05-27 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5e8f1a3d7b2"
down_revision: Union[str, None] = "b7c1e9fa20d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workshop_enrollment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workshop_id", sa.Uuid(), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workshop_id"],
            ["workshop.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "workshop_id",
            name="uq_workshop_enrollment_user_workshop",
        ),
    )
    op.create_index(
        "ix_workshop_enrollment_user_id",
        "workshop_enrollment",
        ["user_id"],
    )
    op.create_index(
        "ix_workshop_enrollment_workshop_id",
        "workshop_enrollment",
        ["workshop_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workshop_enrollment_workshop_id",
        table_name="workshop_enrollment",
    )
    op.drop_index(
        "ix_workshop_enrollment_user_id",
        table_name="workshop_enrollment",
    )
    op.drop_table("workshop_enrollment")
