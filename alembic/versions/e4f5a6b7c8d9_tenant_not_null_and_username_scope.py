"""tenant not null + per-workspace username uniqueness (step 3.1)

Этап 0.5 мультитенантности, шаг 3 из 3 — эта миграция закрывает часть,
касающуюся схемы БД:
  - workspace_id становится NOT NULL на всех 12 tenant-таблицах.
    audit_log НЕ трогаем — там workspace_id остаётся nullable намеренно
    (ondelete="SET NULL": история изменений должна пережить удаление
    компании, см. миграцию cb2a8b3114f7 и src/models/audit.py).
  - username перестаёт быть уникальным глобально (users_username_key) и
    становится уникальным в рамках workspace — двум компаниям больше не
    нужно делить одно пространство имён "Иван Иванов".
  - login НЕ трогаем: остаётся nullable и уникален глобально, как решили
    (вход только по login, но login сейчас проставляет только бот —
    задача сделать его обязательным для веб-регистрации и админки, с
    backfill для существующих пользователей, вынесена в отдельную
    миграцию/PR, а не сделана здесь заодно).

Предпосылка: миграция d3e4f5a6b7c8 (backfill Default workspace) уже
применена, то есть workspace_id нигде не NULL. Если это не так, ALTER
COLUMN ... SET NOT NULL упадёт с понятной ошибкой — это и есть защита от
случайного пропуска шага 2. Проверено: при попытке применить эту миграцию
к базе, где workspace_id ещё NULL, Alembic откатывает всю транзакцию и
БД остаётся на предыдущей версии — частично применённой миграции не
бывает.

Откат (downgrade) необратим по сути, а не только по коду: если к моменту
отката в разных компаниях уже появились пользователи с одинаковым
username (то, ради чего эта миграция и делалась), восстановление
глобального UNIQUE(username) упадёт с той же ошибкой на дубликате —
это ожидаемо, а не баг, и подтверждено на тестовых данных.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-29
"""

from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None

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


def upgrade() -> None:
    for table in _TENANT_TABLES:
        op.alter_column(table, "workspace_id", nullable=False)

    op.drop_constraint("users_username_key", "users", type_="unique")
    op.create_unique_constraint("uq_users_workspace_username", "users", ["workspace_id", "username"])


def downgrade() -> None:
    op.drop_constraint("uq_users_workspace_username", "users", type_="unique")
    op.create_unique_constraint("users_username_key", "users", ["username"])

    for table in _TENANT_TABLES:
        op.alter_column(table, "workspace_id", nullable=True)
