"""add scheduled_events.reminded_at and notification_settings.notify_event_reminder

Напоминание о скорой встрече/звонке: отметка «напомнили» на событии и переключатель в настройках уведомлений.

Revision ID: m8b9c0d1e2f3
Revises: l7a8b9c0d1e2
Create Date: 2026-10-15
"""

import sqlalchemy as sa

from alembic import op

revision = "m8b9c0d1e2f3"
down_revision = "l7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scheduled_events", sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "notification_settings",
        sa.Column("notify_event_reminder", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("notification_settings", "notify_event_reminder")
    op.drop_column("scheduled_events", "reminded_at")
