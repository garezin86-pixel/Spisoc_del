"""add_group_notification_fields

Revision ID: 8cf038c5b3df
Revises: 1baf19df01f1
Create Date: 2026-05-14 15:21:09.453420

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8cf038c5b3df"
down_revision: Union[str, Sequence[str], None] = "1baf19df01f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавление колонки notify_group_assigned и полей времени (только если их нет)"""

    # Проверяем существующие колонки
    inspector = sa.inspect(op.get_bind())
    existing_columns = [
        col["name"] for col in inspector.get_columns("notification_settings")
    ]

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
        op.create_index(
            "ix_notification_settings_notify_group_assigned",
            "notification_settings",
            ["notify_group_assigned"],
            unique=False,
        )

    if "created_at" not in existing_columns:
        op.add_column(
            "notification_settings",
            sa.Column(
                "created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()
            ),
        )

    if "updated_at" not in existing_columns:
        op.add_column(
            "notification_settings",
            sa.Column(
                "updated_at", sa.DateTime(), nullable=True, onupdate=sa.func.now()
            ),
        )


def downgrade() -> None:
    """Удаление добавленных колонок (если они есть)"""

    inspector = sa.inspect(op.get_bind())
    existing_columns = [
        col["name"] for col in inspector.get_columns("notification_settings")
    ]

    if "notify_group_assigned" in existing_columns:
        op.drop_index(
            "ix_notification_settings_notify_group_assigned",
            table_name="notification_settings",
        )
        op.drop_column("notification_settings", "notify_group_assigned")

    if "updated_at" in existing_columns:
        op.drop_column("notification_settings", "updated_at")

    if "created_at" in existing_columns:
        op.drop_column("notification_settings", "created_at")
