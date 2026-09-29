"""add workspaces and workspace_id (step 1 of 3, nullable)

Этап 0.5 мультитенантности, шаг 1 из 3:
  1. (эта миграция) создать workspaces, добавить nullable workspace_id
     во все таблицы компании.
  2. (следующая миграция) заполнить существующие строки id Default
     workspace (data-миграция).
  3. (следующая миграция) NOT NULL + уникальность login/username в рамках
     workspace.

Специально НЕ через `alembic revision --autogenerate`: автодифф на этой базе
предлагал попутно снести/пересоздать десяток частичных и функциональных
индексов, которые не отражены в ORM-моделях (partial index на comments,
gin по title+description, recurrence_active и т.п.) — они создавались
напрямую через op.create_index в старых миграциях и autogenerate видит их
как "лишние". Трогать их — не задача этой миграции, поэтому файл написан
вручную и меняет только то, что относится к workspace_id.

Revision ID: cb2a8b3114f7
Revises: 342cd9c75837
Create Date: 2026-09-28
"""

import sqlalchemy as sa

from alembic import op

revision = "cb2a8b3114f7"
down_revision = "342cd9c75837"
branch_labels = None
depends_on = None

# Таблицы компании, получающие прямой workspace_id. Дочерние таблицы
# (checklist-пункты задачи, вложения, комментарии) размечаются тоже —
# так фильтр по workspace работает без JOIN к родителю.
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
]

# audit_log обрабатывается отдельно: ondelete="SET NULL" (запись истории не
# должна исчезать при удалении компании), у остальных — RESTRICT (нельзя
# удалить workspace, пока в нём есть данные, см. src/models/mixins.py).
_AUDIT_TABLE = "audit_log"


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)

    for table in _TENANT_TABLES:
        op.add_column(table, sa.Column("workspace_id", sa.Integer(), nullable=True))
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
        op.create_foreign_key(
            f"fk_{table}_workspace_id",
            table,
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.add_column(_AUDIT_TABLE, sa.Column("workspace_id", sa.Integer(), nullable=True))
    op.create_index(f"ix_{_AUDIT_TABLE}_workspace_id", _AUDIT_TABLE, ["workspace_id"])
    op.create_foreign_key(
        f"fk_{_AUDIT_TABLE}_workspace_id",
        _AUDIT_TABLE,
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(f"fk_{_AUDIT_TABLE}_workspace_id", _AUDIT_TABLE, type_="foreignkey")
    op.drop_index(f"ix_{_AUDIT_TABLE}_workspace_id", table_name=_AUDIT_TABLE)
    op.drop_column(_AUDIT_TABLE, "workspace_id")

    for table in reversed(_TENANT_TABLES):
        op.drop_constraint(f"fk_{table}_workspace_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_column(table, "workspace_id")

    op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.drop_table("workspaces")
