"""add_deleted_at_to_workshop

Revision ID: c93be6b1f993
Revises: 8a6a02aec077
Create Date: 2026-03-22 13:57:17.030560

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c93be6b1f993"
down_revision: Union[str, None] = "8a6a02aec077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    workshop_columns = {column["name"] for column in inspector.get_columns("workshop")}
    workshop_indexes = {index["name"] for index in inspector.get_indexes("workshop")}

    if "deleted_at" not in workshop_columns:
        op.add_column("workshop", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    if op.f("ix_workshop_deleted_at") not in workshop_indexes:
        op.create_index(
            op.f("ix_workshop_deleted_at"),
            "workshop",
            ["deleted_at"],
            unique=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    workshop_columns = {column["name"] for column in inspector.get_columns("workshop")}
    workshop_indexes = {index["name"] for index in inspector.get_indexes("workshop")}

    if op.f("ix_workshop_deleted_at") in workshop_indexes:
        op.drop_index(op.f("ix_workshop_deleted_at"), table_name="workshop")
    if "deleted_at" in workshop_columns:
        op.drop_column("workshop", "deleted_at")
