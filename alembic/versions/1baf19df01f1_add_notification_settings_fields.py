# alembic/versions/1baf19df01f1_add_notification_settings_fields.py
"""add_notification_settings_fields

Revision ID: 1baf19df01f1
Revises: 7c53145af9bd
Create Date: 2026-05-14 10:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "1baf19df01f1"
down_revision = "7c53145af9bd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Получаем список существующих колонок
    inspector = sa.inspect(op.get_bind())
    existing_columns = [col["name"] for col in inspector.get_columns("notification_settings")]

    # Добавляем только отсутствующие колонки
    if "notify_group_assigned" not in existing_columns:
        op.add_column(
            "notification_settings",
            sa.Column(
                "notify_group_assigned",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
        )

    if "notify_task_assigned" not in existing_columns:
        op.add_column(
            "notification_settings",
            sa.Column(
                "notify_task_assigned",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
        )

    if "notify_task_updated" not in existing_columns:
        op.add_column(
            "notification_settings",
            sa.Column(
                "notify_task_updated",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
        )

    if "notify_comment" not in existing_columns:
        op.add_column(
            "notification_settings",
            sa.Column("notify_comment", sa.Boolean(), nullable=False, server_default="true"),
        )

    if "created_at" not in existing_columns:
        op.add_column(
            "notification_settings",
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        )

    if "updated_at" not in existing_columns:
        op.add_column(
            "notification_settings",
            sa.Column("updated_at", sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        )


def downgrade() -> None:
    # Удаляем колонки (если они есть)
    inspector = sa.inspect(op.get_bind())
    existing_columns = [col["name"] for col in inspector.get_columns("notification_settings")]

    if "notify_group_assigned" in existing_columns:
        op.drop_column("notification_settings", "notify_group_assigned")
    if "notify_comment" in existing_columns:
        op.drop_column("notification_settings", "notify_comment")
    if "notify_task_updated" in existing_columns:
        op.drop_column("notification_settings", "notify_task_updated")
    if "notify_task_assigned" in existing_columns:
        op.drop_column("notification_settings", "notify_task_assigned")
    if "updated_at" in existing_columns:
        op.drop_column("notification_settings", "updated_at")
    if "created_at" in existing_columns:
        op.drop_column("notification_settings", "created_at")
