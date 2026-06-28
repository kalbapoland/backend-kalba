"""add kicked_at to workshop_participant

Revision ID: c1f4a9b2e8d7
Revises: b8e4c2f10937
Create Date: 2026-06-28 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1f4a9b2e8d7"
down_revision: Union[str, None] = "b8e4c2f10937"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workshop_participant",
        sa.Column("kicked_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workshop_participant", "kicked_at")
