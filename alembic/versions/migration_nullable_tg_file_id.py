"""make telegram_file_id nullable for web uploads

Revision ID: d4b6e8f2a1c3
Revises: c3a5e9f1b7d2
Create Date: 2025-07-01

Теперь поле telegram_file_id может быть NULL — для вложений,
загруженных через веб-интерфейс (POST /api/attachments/tasks/{id}),
а не через Telegram-бота.
"""

import sqlalchemy as sa

from alembic import op

revision = "d4b6e8f2a1c3"
down_revision = "c3a5e9f1b7d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "attachments",
        "telegram_file_id",
        existing_type=sa.String(255),
        nullable=True,
    )


def downgrade() -> None:
    # Заполняем NULL-значения заглушкой перед возвратом к NOT NULL
    op.execute("UPDATE attachments SET telegram_file_id = 'web_upload' WHERE telegram_file_id IS NULL")
    op.alter_column(
        "attachments",
        "telegram_file_id",
        existing_type=sa.String(255),
        nullable=False,
    )
