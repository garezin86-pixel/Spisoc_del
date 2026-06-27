"""create audit_log table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-19 10:05:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

_ACTIONS = ("create", "update", "delete", "restore")


def upgrade() -> None:
    # Создаём enum тип
    audit_action = postgresql.ENUM(*_ACTIONS, name="audit_action_enum", create_type=True)
    audit_action.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "action",
            postgresql.ENUM(*_ACTIONS, name="audit_action_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("old_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # История конкретной записи
    op.create_index(
        "ix_audit_log_entity",
        "audit_log",
        ["entity_type", "entity_id", "changed_at"],
    )
    # Все действия пользователя
    op.create_index(
        "ix_audit_log_user_id",
        "audit_log",
        ["user_id", "changed_at"],
    )
    # Фильтр по типу действия (все удаления, все создания...)
    op.create_index(
        "ix_audit_log_action",
        "audit_log",
        ["action", "changed_at"],
    )
    # Временной диапазон — для отчётов и архивирования
    op.create_index(
        "ix_audit_log_changed_at",
        "audit_log",
        ["changed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_changed_at", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_user_id", table_name="audit_log")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_table("audit_log")

    audit_action = postgresql.ENUM(*_ACTIONS, name="audit_action_enum")
    audit_action.drop(op.get_bind(), checkfirst=True)
