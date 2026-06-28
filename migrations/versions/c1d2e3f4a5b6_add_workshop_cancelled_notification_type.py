"""add workshop_cancelled notification type

Revision ID: c1d2e3f4a5b6
Revises: b8e4c2f10937
Create Date: 2026-06-28 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b8e4c2f10937"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE usernotificationtype ADD VALUE IF NOT EXISTS 'workshop_cancelled'")


def downgrade() -> None:
    # Postgres does not support removing enum values without recreating the type.
    # Delete any records using this value so the value is unused after downgrade.
    op.execute("DELETE FROM user_notification WHERE type = 'workshop_cancelled'")
