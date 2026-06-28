"""add group_deleted notification type

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-29 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE usernotificationtype ADD VALUE IF NOT EXISTS 'group_deleted'")


def downgrade() -> None:
    # Postgres does not support removing enum values without recreating the type.
    # Delete any records using this value so the value is unused after downgrade.
    op.execute("DELETE FROM user_notification WHERE type = 'group_deleted'")
