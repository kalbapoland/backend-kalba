"""add workshop reminder fields

Revision ID: d2f8a3c4e9b0
Revises: b1d4e7f2a8c9
Create Date: 2026-04-25 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2f8a3c4e9b0"
down_revision: Union[str, None] = "b1d4e7f2a8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Index names — kept as plain strings so the existence check (which compares
# against `inspector.get_indexes()` raw names) is reliable.
_REMINDER_SENT_AT_INDEX = "ix_workshop_reminder_sent_at"
_DUE_REMINDERS_INDEX = "ix_workshop_due_reminders"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    workshop_columns = {column["name"] for column in inspector.get_columns("workshop")}
    workshop_indexes = {index["name"] for index in inspector.get_indexes("workshop")}

    if "reminder_minutes_before" not in workshop_columns:
        # Use a transient server_default for backfill; on PG 11+ ADD COLUMN with
        # a constant default is metadata-only (no table rewrite). Drop the default
        # afterwards so the application owns the value going forward.
        op.add_column(
            "workshop",
            sa.Column(
                "reminder_minutes_before",
                sa.Integer(),
                nullable=False,
                server_default="60",
            ),
        )
        op.alter_column("workshop", "reminder_minutes_before", server_default=None)

    if "reminder_sent_at" not in workshop_columns:
        op.add_column(
            "workshop",
            sa.Column("reminder_sent_at", sa.DateTime(), nullable=True),
        )

    if _REMINDER_SENT_AT_INDEX not in workshop_indexes:
        op.create_index(
            _REMINDER_SENT_AT_INDEX,
            "workshop",
            ["reminder_sent_at"],
            unique=False,
        )

    # Partial index that matches the scheduler's hot-path query exactly
    # (deleted_at IS NULL AND reminder_sent_at IS NULL ordered by start_time).
    # Only un-sent, live workshops are scanned — the index stays small.
    if _DUE_REMINDERS_INDEX not in workshop_indexes:
        op.create_index(
            _DUE_REMINDERS_INDEX,
            "workshop",
            ["start_time"],
            unique=False,
            postgresql_where=sa.text(
                "deleted_at IS NULL AND reminder_sent_at IS NULL"
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    workshop_columns = {column["name"] for column in inspector.get_columns("workshop")}
    workshop_indexes = {index["name"] for index in inspector.get_indexes("workshop")}

    if _DUE_REMINDERS_INDEX in workshop_indexes:
        op.drop_index(_DUE_REMINDERS_INDEX, table_name="workshop")
    if _REMINDER_SENT_AT_INDEX in workshop_indexes:
        op.drop_index(_REMINDER_SENT_AT_INDEX, table_name="workshop")
    if "reminder_sent_at" in workshop_columns:
        op.drop_column("workshop", "reminder_sent_at")
    if "reminder_minutes_before" in workshop_columns:
        op.drop_column("workshop", "reminder_minutes_before")
