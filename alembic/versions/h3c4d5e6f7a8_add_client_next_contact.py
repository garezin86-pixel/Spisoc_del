"""add clients.next_contact_at and notify_contact_due

Напоминания «связаться снова»: дата следующего контакта у клиента, служебная отметка «напомнили»
и переключатель уведомления в настройках пользователя (по умолчанию включён).

Revision ID: h3c4d5e6f7a8
Revises: g2b3c4d5e6f7
Create Date: 2026-10-11
"""

import sqlalchemy as sa

from alembic import op

revision = "h3c4d5e6f7a8"
down_revision = "g2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("next_contact_at", sa.Date(), nullable=True))
    op.add_column("clients", sa.Column("next_contact_notified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_clients_next_contact_at", "clients", ["next_contact_at"])
    op.add_column(
        "notification_settings",
        sa.Column("notify_contact_due", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("notification_settings", "notify_contact_due")
    op.drop_index("ix_clients_next_contact_at", table_name="clients")
    op.drop_column("clients", "next_contact_notified_at")
    op.drop_column("clients", "next_contact_at")
