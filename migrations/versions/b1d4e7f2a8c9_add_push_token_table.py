"""add push_token table

Revision ID: b1d4e7f2a8c9
Revises: aa7f95d38cb2
Create Date: 2026-04-25 13:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1d4e7f2a8c9"
down_revision: Union[str, None] = "aa7f95d38cb2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "push_token" not in existing_tables:
        op.create_table(
            "push_token",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("token", sa.String(), nullable=False),
            sa.Column(
                "platform",
                sa.Enum("ios", "android", name="pushplatform"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token"),
        )
        op.create_index(
            op.f("ix_push_token_user_id"),
            "push_token",
            ["user_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_push_token_token"),
            "push_token",
            ["token"],
            unique=True,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "push_token" in existing_tables:
        op.drop_index(op.f("ix_push_token_token"), table_name="push_token")
        op.drop_index(op.f("ix_push_token_user_id"), table_name="push_token")
        op.drop_table("push_token")
        sa.Enum(name="pushplatform").drop(op.get_bind(), checkfirst=True)
