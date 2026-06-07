"""add priority to tasks

Revision ID: b3d4e5f6a7c8
Revises: f35f41e6ffc8
Create Date: 2026-06-07 18:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b3d4e5f6a7c8"
down_revision: Union[str, Sequence[str], None] = "f35f41e6ffc8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создаём enum тип в PostgreSQL
    op.execute("CREATE TYPE taskpriority AS ENUM ('low', 'medium', 'high', 'critical')")

    # Добавляем колонку с дефолтным значением medium
    op.add_column(
        "spisok_del",
        sa.Column(
            "priority",
            sa.Enum("low", "medium", "high", "critical", name="taskpriority"),
            nullable=False,
            server_default="medium",
        ),
    )

    # Индекс для фильтрации по приоритету
    op.create_index("ix_spisok_del_priority", "spisok_del", ["priority"])

    # Составной индекс: приоритет + статус (частый запрос)
    op.create_index(
        "ix_spisok_del_priority_done", "spisok_del", ["priority", "is_done"]
    )


def downgrade() -> None:
    op.drop_index("ix_spisok_del_priority_done", table_name="spisok_del")
    op.drop_index("ix_spisok_del_priority", table_name="spisok_del")
    op.drop_column("spisok_del", "priority")
    op.execute("DROP TYPE taskpriority")
