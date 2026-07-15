"""add completed_at to spisok_del

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-11

completed_at — точный момент перехода в status=done, для аналитики
"закрыто в срок/не в срок" по исполнителям и проектам. Отдельно от
updated_at, который трогается при любом изменении задачи.

Бэкфилл для уже существующих done-задач: используем updated_at как
приближение (лучшее, что у нас есть задним числом) — новые переходы
в done дальше будут писать completed_at точно, через хук в TaskService.
"""

import sqlalchemy as sa

from alembic import op

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("spisok_del", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))

    # Бэкфилл: для уже завершённых задач используем updated_at как
    # приближение реального момента завершения (точных данных задним числом
    # нет — это единственный уже имеющийся timestamp, близкий по смыслу).
    op.execute(
        """
        UPDATE spisok_del
        SET completed_at = updated_at
        WHERE status = 'done' AND completed_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("spisok_del", "completed_at")
