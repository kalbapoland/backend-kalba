"""add password reset token table

Revision ID: a7d3f1c8b204
Revises: e1a2b3c4d5f6
Create Date: 2026-06-02 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7d3f1c8b204"
down_revision: Union[str, None] = "e1a2b3c4d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_token",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_password_reset_token_user_id"),
        "password_reset_token",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_password_reset_token_token_hash"),
        "password_reset_token",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_password_reset_token_token_hash"),
        table_name="password_reset_token",
    )
    op.drop_index(
        op.f("ix_password_reset_token_user_id"),
        table_name="password_reset_token",
    )
    op.drop_table("password_reset_token")
