"""merge reminder and native auth heads

Revision ID: 3b9e2c1d4f50
Revises: d2f8a3c4e9b0, f4a7c1b2d9e0
Create Date: 2026-04-27 19:20:00.000000

"""

from typing import Sequence, Union


revision: str = "3b9e2c1d4f50"
down_revision: Union[str, Sequence[str], None] = (
    "d2f8a3c4e9b0",
    "f4a7c1b2d9e0",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass