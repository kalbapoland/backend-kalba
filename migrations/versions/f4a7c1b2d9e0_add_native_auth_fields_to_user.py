"""add native auth fields to user

Revision ID: f4a7c1b2d9e0
Revises: e8c1f2a9b3d6
Create Date: 2026-04-27 13:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4a7c1b2d9e0"
down_revision: Union[str, None] = "e8c1f2a9b3d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("hashed_password", sa.String(), nullable=True),
    )
    op.alter_column(
        "user",
        "google_id",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE \"user\" SET google_id = email WHERE google_id IS NULL")
    op.alter_column(
        "user",
        "google_id",
        existing_type=sa.String(),
        nullable=False,
    )
    op.drop_column("user", "hashed_password")