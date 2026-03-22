"""migrate_specialties_to_json_array

Revision ID: 8a6a02aec077
Revises: 59b3a5b0396b
Create Date: 2026-03-22 13:50:27.059255

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '8a6a02aec077'
down_revision: Union[str, None] = '59b3a5b0396b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new JSON column
    op.add_column(
        "trainer_profile",
        sa.Column("specialties_json", sa.JSON(), nullable=True),
    )

    # Migrate data: convert "yoga,meditation" → ["yoga", "meditation"]
    op.execute("""
        UPDATE trainer_profile
        SET specialties_json = CASE
            WHEN specialties = '' THEN '[]'::json
            ELSE (
                SELECT json_agg(trim(s))
                FROM unnest(string_to_array(specialties, ',')) AS s
            )
        END
    """)

    # Make the new column non-nullable with empty array default
    op.alter_column("trainer_profile", "specialties_json", nullable=False)

    # Drop old column and rename new one
    op.drop_column("trainer_profile", "specialties")
    op.alter_column("trainer_profile", "specialties_json", new_column_name="specialties")


def downgrade() -> None:
    # Add back text column
    op.add_column(
        "trainer_profile",
        sa.Column("specialties_str", sa.String(), nullable=True),
    )

    # Convert JSON array back to comma-separated string
    op.execute("""
        UPDATE trainer_profile
        SET specialties_str = (
            SELECT string_agg(value, ',')
            FROM json_array_elements_text(specialties)
        )
    """)

    op.alter_column("trainer_profile", "specialties_str", nullable=False, server_default="''")
    op.drop_column("trainer_profile", "specialties")
    op.alter_column("trainer_profile", "specialties_str", new_column_name="specialties")
