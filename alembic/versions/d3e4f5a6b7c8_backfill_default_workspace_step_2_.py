"""backfill default workspace (step 2 of 3)

Этап 0.5 мультитенантности, шаг 2 из 3:
  1. (сделано) создать workspaces, добавить nullable workspace_id.
  2. (эта миграция) создать Default workspace и проставить его id всем
     существующим строкам, у которых workspace_id ещё NULL.
  3. (следующая миграция) NOT NULL + уникальность login/username в рамках
     workspace.

Идемпотентна: повторный запуск не создаст второй Default и не тронет строки,
у которых workspace_id уже заполнен (например, если часть данных успела
попасть в БД между шагом 1 и этим деплоем).

Revision ID: d3e4f5a6b7c8
Revises: cb2a8b3114f7
Create Date: 2026-09-28
"""

import sqlalchemy as sa

from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "cb2a8b3114f7"
branch_labels = None
depends_on = None

# Тот же slug, что DEFAULT_WORKSPACE_SLUG в src/models/workspace.py. Не
# импортируем модель из миграции намеренно (миграции должны переживать
# будущие изменения моделей), поэтому значение продублировано — если меняете
# slug в модели, поменяйте и здесь.
_DEFAULT_SLUG = "default"

# Порядок важен только для читаемости; на nullable-колонки FK не давит.
_TENANT_TABLES = [
    "users",
    "groups",
    "projects",
    "spisok_del",
    "tags",
    "task_templates",
    "webhooks",
    "chat_messages",
    "comments",
    "attachments",
    "task_dependencies",
    "task_checklist_items",
    "audit_log",
]


def upgrade() -> None:
    conn = op.get_bind()

    # INSERT ... ON CONFLICT — на случай повторного запуска (idempotent).
    conn.execute(
        sa.text(
            """
            INSERT INTO workspaces (name, slug, is_active, created_at)
            VALUES (:name, :slug, true, now())
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        {"name": "Default", "slug": _DEFAULT_SLUG},
    )
    default_id = conn.execute(
        sa.text("SELECT id FROM workspaces WHERE slug = :slug"),
        {"slug": _DEFAULT_SLUG},
    ).scalar_one()

    for table in _TENANT_TABLES:
        conn.execute(
            sa.text(f"UPDATE {table} SET workspace_id = :ws WHERE workspace_id IS NULL"),  # noqa: S608
            {"ws": default_id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    default_id = conn.execute(
        sa.text("SELECT id FROM workspaces WHERE slug = :slug"),
        {"slug": _DEFAULT_SLUG},
    ).scalar_one_or_none()
    if default_id is None:
        return

    # Только строки, реально проставленные этой миграцией — если после
    # шага 2 кто-то успел явно назначить Default другому пользователю по
    # своей воле, откат их не трогает... на практике на этом этапе Default
    # присвоен всем, так что просто возвращаем NULL везде, где сейчас стоит
    # default_id.
    for table in reversed(_TENANT_TABLES):
        conn.execute(
            sa.text(f"UPDATE {table} SET workspace_id = NULL WHERE workspace_id = :ws"),  # noqa: S608
            {"ws": default_id},
        )

    conn.execute(sa.text("DELETE FROM workspaces WHERE id = :ws"), {"ws": default_id})
