"""add task status for kanban

Revision ID: add_task_status_kanban
Revises: <ЗАМЕНИ_НА_ПОСЛЕДНИЙ_REVISION_ID>
Create Date: 2026-06-15

ИНСТРУКЦИЯ:
1. Положи этот файл в migrations/versions/
2. Замени Revises ниже на ID последней миграции:
   alembic history --verbose  (последняя строка = последний revision)
3. alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "add_task_status_kanban"
down_revision = "d5e6f7a8b9c0"  # ← ЗАМЕНИ ЗДЕСЬ
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Создаём тип ENUM в PostgreSQL
    taskstatus = postgresql.ENUM(
        "backlog",
        "todo",
        "in_progress",
        "review",
        "done",
        name="taskstatus",
        create_type=False,
    )
    taskstatus.create(op.get_bind(), checkfirst=True)

    # 2. Добавляем колонку status с дефолтом 'todo'
    op.add_column(
        "spisok_del",
        sa.Column(
            "status",
            sa.Enum(
                "backlog",
                "todo",
                "in_progress",
                "review",
                "done",
                name="taskstatus",
            ),
            nullable=False,
            server_default="todo",
        ),
    )

    # 3. Переносим данные из is_done → status
    op.execute("UPDATE spisok_del SET status = 'done' WHERE is_done = true")
    op.execute("UPDATE spisok_del SET status = 'todo' WHERE is_done = false")

    # 4. Индексы для канбан-запросов
    op.create_index("ix_spisok_del_status", "spisok_del", ["status"])
    op.create_index("ix_spisok_del_user_status", "spisok_del", ["user_id", "status"])
    op.create_index(
        "ix_spisok_del_project_status", "spisok_del", ["project_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_spisok_del_project_status", table_name="spisok_del")
    op.drop_index("ix_spisok_del_user_status", table_name="spisok_del")
    op.drop_index("ix_spisok_del_status", table_name="spisok_del")
    op.drop_column("spisok_del", "status")
    op.execute("DROP TYPE IF EXISTS taskstatus")
