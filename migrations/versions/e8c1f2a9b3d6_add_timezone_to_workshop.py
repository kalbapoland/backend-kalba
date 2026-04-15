"""add timezone to workshop

Revision ID: e8c1f2a9b3d6
Revises: c93be6b1f993
Create Date: 2026-04-14 21:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8c1f2a9b3d6"
down_revision: Union[str, None] = "c93be6b1f993"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workshop",
        sa.Column(
            "timezone",
            sa.String(),
            nullable=False,
            server_default="UTC",
        ),
    )


def downgrade() -> None:
    op.drop_column("workshop", "timezone")
