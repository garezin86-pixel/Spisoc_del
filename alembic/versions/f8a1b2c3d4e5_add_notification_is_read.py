# alembic/versions/e1f2a3b4c5d6_add_notification_is_read.py
"""add_notification_is_read

Добавляет is_read к notification_logs — таблица уже пишется автоматически
при каждой отправке уведомления (см. src/services/notifications.py), теперь
она же служит источником данных для колокольчика в шапке ("прочитано /
не прочитано"), отдельная таблица не нужна.

Revision ID: f8a1b2c3d4e5
Revises: a8b6c0d2e4f7
Create Date: 2026-08-05 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "f8a1b2c3d4e5"
down_revision = "a8b6c0d2e4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = [col["name"] for col in inspector.get_columns("notification_logs")]

    if "is_read" not in existing_columns:
        op.add_column(
            "notification_logs",
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        )
        op.create_index(
            "ix_notification_logs_user_is_read",
            "notification_logs",
            ["user_id", "is_read"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = [col["name"] for col in inspector.get_columns("notification_logs")]
    existing_indexes = [ix["name"] for ix in inspector.get_indexes("notification_logs")]

    if "ix_notification_logs_user_is_read" in existing_indexes:
        op.drop_index("ix_notification_logs_user_is_read", table_name="notification_logs")
    if "is_read" in existing_columns:
        op.drop_column("notification_logs", "is_read")
