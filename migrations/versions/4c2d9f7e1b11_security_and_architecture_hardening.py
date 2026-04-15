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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

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

    tables = set(inspector.get_table_names())
    if "refresh_token" not in tables:
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

    refresh_indexes = {
        index["name"] for index in inspector.get_indexes("refresh_token")
    }
    if op.f("ix_refresh_token_token_hash") not in refresh_indexes:
        op.create_index(
            op.f("ix_refresh_token_token_hash"),
            "refresh_token",
            ["token_hash"],
            unique=True,
        )
    if op.f("ix_refresh_token_user_id") not in refresh_indexes:
        op.create_index(
            op.f("ix_refresh_token_user_id"),
            "refresh_token",
            ["user_id"],
            unique=False,
        )

    trainer_columns = {
        column["name"]: column for column in inspector.get_columns("trainer_profile")
    }
    specialties_column = trainer_columns.get("specialties")
    if specialties_column is not None and not isinstance(
        specialties_column["type"],
        (sa.JSON, postgresql.JSONB),
    ):
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
        op.alter_column(
            "trainer_profile",
            "specialties_new",
            new_column_name="specialties",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    trainer_columns = {
        column["name"]: column for column in inspector.get_columns("trainer_profile")
    }
    specialties_column = trainer_columns.get("specialties")
    if specialties_column is not None and isinstance(
        specialties_column["type"],
        (sa.JSON, postgresql.JSONB),
    ):
        op.add_column(
            "trainer_profile",
            sa.Column(
                "specialties_old", sa.String(), nullable=False, server_default=""
            ),
        )
        op.execute(
            """
            UPDATE trainer_profile
            SET specialties_old = CASE
                WHEN jsonb_typeof(specialties::jsonb) = 'array' THEN array_to_string(
                    ARRAY(SELECT jsonb_array_elements_text(specialties::jsonb)),
                    ','
                )
                ELSE ''
            END
            """
        )
        op.drop_column("trainer_profile", "specialties")
        op.alter_column(
            "trainer_profile",
            "specialties_old",
            new_column_name="specialties",
        )

    tables = set(inspector.get_table_names())
    if "refresh_token" in tables:
        refresh_indexes = {
            index["name"] for index in inspector.get_indexes("refresh_token")
        }
        if op.f("ix_refresh_token_user_id") in refresh_indexes:
            op.drop_index(op.f("ix_refresh_token_user_id"), table_name="refresh_token")
        if op.f("ix_refresh_token_token_hash") in refresh_indexes:
            op.drop_index(
                op.f("ix_refresh_token_token_hash"),
                table_name="refresh_token",
            )
        op.drop_table("refresh_token")

    workshop_columns = {column["name"] for column in inspector.get_columns("workshop")}
    workshop_indexes = {index["name"] for index in inspector.get_indexes("workshop")}
    if op.f("ix_workshop_deleted_at") in workshop_indexes:
        op.drop_index(op.f("ix_workshop_deleted_at"), table_name="workshop")
    if "deleted_at" in workshop_columns:
        op.drop_column("workshop", "deleted_at")
