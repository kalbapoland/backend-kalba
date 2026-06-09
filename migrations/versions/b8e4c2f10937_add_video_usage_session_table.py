"""add video usage session table

Revision ID: b8e4c2f10937
Revises: a7d3f1c8b204
Create Date: 2026-06-09 22:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8e4c2f10937"
down_revision: Union[str, None] = "a7d3f1c8b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "video_usage_session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workshop_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("reserved_minutes", sa.Integer(), nullable=False),
        sa.Column("actual_minutes", sa.Integer(), nullable=True),
        sa.Column("settled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["workshop_id"], ["workshop.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_video_usage_session_workshop_id"),
        "video_usage_session",
        ["workshop_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_video_usage_session_user_id"),
        "video_usage_session",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_video_usage_session_settled"),
        "video_usage_session",
        ["settled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_video_usage_session_created_at"),
        "video_usage_session",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_video_usage_session_created_at"),
        table_name="video_usage_session",
    )
    op.drop_index(
        op.f("ix_video_usage_session_settled"),
        table_name="video_usage_session",
    )
    op.drop_index(
        op.f("ix_video_usage_session_user_id"),
        table_name="video_usage_session",
    )
    op.drop_index(
        op.f("ix_video_usage_session_workshop_id"),
        table_name="video_usage_session",
    )
    op.drop_table("video_usage_session")
