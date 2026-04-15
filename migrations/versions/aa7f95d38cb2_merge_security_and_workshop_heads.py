"""merge security and workshop heads

Revision ID: aa7f95d38cb2
Revises: 4c2d9f7e1b11, e8c1f2a9b3d6
Create Date: 2026-04-15 08:15:00.000000

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "aa7f95d38cb2"
down_revision: Union[str, tuple[str, str], None] = (
    "4c2d9f7e1b11",
    "e8c1f2a9b3d6",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
