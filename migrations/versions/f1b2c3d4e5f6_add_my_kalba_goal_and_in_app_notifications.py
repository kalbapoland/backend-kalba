"""add my kalba goal and in-app notifications

Revision ID: f1b2c3d4e5f6
Revises: c5e8f1a3d7b2
Create Date: 2026-05-28 11:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, None] = "c5e8f1a3d7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_goal",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("monthly_target", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("monthly_target >= 1", name="ck_user_goal_monthly_target_min"),
        sa.CheckConstraint("monthly_target <= 60", name="ck_user_goal_monthly_target_max"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(op.f("ix_user_goal_user_id"), "user_goal", ["user_id"], unique=True)

    op.create_table(
        "user_notification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("workshop_rescheduled", "workshop_reminder", name="usernotificationtype"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_notification_user_id"), "user_notification", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_user_notification_is_read"), "user_notification", ["is_read"], unique=False
    )
    op.create_index(
        op.f("ix_user_notification_created_at"), "user_notification", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_user_notification_deleted_at"), "user_notification", ["deleted_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_notification_deleted_at"), table_name="user_notification")
    op.drop_index(op.f("ix_user_notification_created_at"), table_name="user_notification")
    op.drop_index(op.f("ix_user_notification_is_read"), table_name="user_notification")
    op.drop_index(op.f("ix_user_notification_user_id"), table_name="user_notification")
    op.drop_table("user_notification")
    sa.Enum(name="usernotificationtype").drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f("ix_user_goal_user_id"), table_name="user_goal")
    op.drop_table("user_goal")
