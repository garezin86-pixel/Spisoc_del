"""add reminder_sent

Revision ID: c88facae7745
Revises: f1a59d8d63c6
Create Date: 2026-05-13 10:58:45.495496
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c88facae7745"
down_revision: Union[str, Sequence[str], None] = "f1a59d8d63c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # 1. Добавляем колонку как nullable
    op.add_column("spisok_del", sa.Column("reminder_sent", sa.Boolean(), nullable=True))

    # 2. Заполняем существующие записи
    op.execute("UPDATE spisok_del SET reminder_sent = FALSE")

    # 3. Делаем NOT NULL
    op.alter_column(
        "spisok_del", "reminder_sent", nullable=False, existing_type=sa.Boolean()
    )

    # 4. Добавляем DEFAULT для новых записей
    op.alter_column(
        "spisok_del",
        "reminder_sent",
        server_default=sa.false(),
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Убираем default
    op.alter_column(
        "spisok_del",
        "reminder_sent",
        server_default=None,
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )

    # Удаляем колонку
    op.drop_column("spisok_del", "reminder_sent")
