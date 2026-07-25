"""add filter_type to filter_presets

Revision ID: d02b61f43b1a
Revises: a6c276774d5f
Create Date: 2026-07-25 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d02b61f43b1a"
down_revision: Union[str, Sequence[str], None] = "a6c276774d5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("filter_presets", sa.Column("filter_type", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("filter_presets", "filter_type")
