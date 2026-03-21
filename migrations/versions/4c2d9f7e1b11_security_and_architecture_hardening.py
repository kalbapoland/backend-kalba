"""security and architecture hardening

Revision ID: 4c2d9f7e1b11
Revises: 59b3a5b0396b
Create Date: 2026-03-21 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "4c2d9f7e1b11"
down_revision: Union[str, None] = "59b3a5b0396b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workshop", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_workshop_deleted_at"), "workshop", ["deleted_at"], unique=False)

    op.create_table(
        "refresh_token",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_refresh_token_token_hash"), "refresh_token", ["token_hash"], unique=True)
    op.create_index(op.f("ix_refresh_token_user_id"), "refresh_token", ["user_id"], unique=False)

    op.add_column(
        "trainer_profile",
        sa.Column(
            "specialties_new",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE trainer_profile
        SET specialties_new = CASE
            WHEN specialties IS NULL OR btrim(specialties) = '' THEN '[]'::jsonb
            ELSE to_jsonb(
                string_to_array(regexp_replace(specialties, '\\s*,\\s*', ',', 'g'), ',')
            )
        END
        """
    )
    op.drop_column("trainer_profile", "specialties")
    op.alter_column("trainer_profile", "specialties_new", new_column_name="specialties")


def downgrade() -> None:
    op.add_column(
        "trainer_profile",
        sa.Column("specialties_old", sa.String(), nullable=False, server_default=""),
    )
    op.execute(
        """
        UPDATE trainer_profile
        SET specialties_old = CASE
            WHEN jsonb_typeof(specialties) = 'array' THEN array_to_string(
                ARRAY(SELECT jsonb_array_elements_text(specialties)),
                ','
            )
            ELSE ''
        END
        """
    )
    op.drop_column("trainer_profile", "specialties")
    op.alter_column("trainer_profile", "specialties_old", new_column_name="specialties")

    op.drop_index(op.f("ix_refresh_token_user_id"), table_name="refresh_token")
    op.drop_index(op.f("ix_refresh_token_token_hash"), table_name="refresh_token")
    op.drop_table("refresh_token")

    op.drop_index(op.f("ix_workshop_deleted_at"), table_name="workshop")
    op.drop_column("workshop", "deleted_at")
