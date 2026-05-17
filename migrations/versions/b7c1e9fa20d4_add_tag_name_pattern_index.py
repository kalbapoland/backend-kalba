"""add text_pattern_ops index on tag.name for prefix autocomplete

Revision ID: b7c1e9fa20d4
Revises: a3f7d24c8e91
Create Date: 2026-05-17 13:45:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "b7c1e9fa20d4"
down_revision: Union[str, None] = "a3f7d24c8e91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The UNIQUE constraint on `tag.name` produces a default-collation B-tree
# index, which Postgres will NOT use for `LIKE 'prefix%'` under locales like
# `en_US.UTF-8`. The autocomplete endpoint (`/api/v1/tags/suggest`) is hit per
# keystroke and would seq-scan `tag` as the table grows; this dedicated
# `text_pattern_ops` index makes prefix lookups index-backed regardless of
# collation.


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tag_name_pattern "
        "ON tag (name text_pattern_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tag_name_pattern")
