"""add_notification_logs_table

Revision ID: 44ccc0086910
Revises: 8cf038c5b3df
Create Date: 2026-05-14 15:32:32.180900

"""

from typing import Sequence, Union

revision: str = "44ccc0086910"
down_revision: Union[str, Sequence[str], None] = "8cf038c5b3df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
