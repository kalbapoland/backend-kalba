"""add group and group_membership tables, workshop.group_id

Revision ID: d7e3b9c1a2f4
Revises: f1b2c3d4e5f6
Create Date: 2026-05-30 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "d7e3b9c1a2f4"
down_revision: Union[str, None] = "f1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # "group" is a reserved SQL keyword; SQLAlchemy auto-quotes the identifier.
    op.create_table(
        "group",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trainer_id", sa.Uuid(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["trainer_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_group_trainer_id", "group", ["trainer_id"])
    op.create_index("ix_group_deleted_at", "group", ["deleted_at"])

    op.create_table(
        "group_membership",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["group.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "group_id", name="uq_group_membership_user_group"
        ),
    )
    op.create_index(
        "ix_group_membership_group_id", "group_membership", ["group_id"]
    )
    op.create_index(
        "ix_group_membership_user_id", "group_membership", ["user_id"]
    )

    op.add_column(
        "workshop",
        sa.Column("group_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_workshop_group_id", "workshop", ["group_id"])
    op.create_foreign_key(
        "fk_workshop_group_id_group",
        "workshop",
        "group",
        ["group_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_workshop_group_id_group", "workshop", type_="foreignkey")
    op.drop_index("ix_workshop_group_id", table_name="workshop")
    op.drop_column("workshop", "group_id")

    op.drop_index("ix_group_membership_user_id", table_name="group_membership")
    op.drop_index("ix_group_membership_group_id", table_name="group_membership")
    op.drop_table("group_membership")

    op.drop_index("ix_group_deleted_at", table_name="group")
    op.drop_index("ix_group_trainer_id", table_name="group")
    op.drop_table("group")
