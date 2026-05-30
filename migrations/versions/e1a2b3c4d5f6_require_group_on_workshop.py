"""require group on workshop (clean up orphans, make group_id NOT NULL)

Revision ID: e1a2b3c4d5f6
Revises: d7e3b9c1a2f4
Create Date: 2026-05-30 14:30:00.000000

Workshops must now belong to a group. Any workshop with no group (e.g. created
before groups existed) is an orphan: its dependent rows and the workshop itself
are deleted, then group_id is made NOT NULL.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, None] = "d7e3b9c1a2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Delete dependent rows of orphan workshops first. workshop_enrollment and
    # workshop_tag cascade on delete, but workshop_rules and workshop_participant
    # do not, so remove them explicitly to avoid FK violations.
    orphans = "SELECT id FROM workshop WHERE group_id IS NULL"
    op.execute(f"DELETE FROM workshop_participant WHERE workshop_id IN ({orphans})")
    op.execute(f"DELETE FROM workshop_rules WHERE workshop_id IN ({orphans})")
    op.execute(f"DELETE FROM workshop_enrollment WHERE workshop_id IN ({orphans})")
    op.execute(f"DELETE FROM workshop_tag WHERE workshop_id IN ({orphans})")
    op.execute("DELETE FROM workshop WHERE group_id IS NULL")

    op.alter_column("workshop", "group_id", existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    op.alter_column("workshop", "group_id", existing_type=sa.Uuid(), nullable=True)
