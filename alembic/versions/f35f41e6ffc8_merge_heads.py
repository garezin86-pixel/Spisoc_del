"""merge heads

Revision ID: f35f41e6ffc8
Revises: a9f3b2c1d8e7, b2c3d4e5f6a7
Create Date: 2026-06-07 13:25:42.531530

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "f35f41e6ffc8"
down_revision: Union[str, Sequence[str], None] = ("a9f3b2c1d8e7", "b2c3d4e5f6a7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
