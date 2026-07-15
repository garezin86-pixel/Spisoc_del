"""add checklist items, tags, and recurrence_rule

Revision ID: e1f2a3b4c5d6
Revises: d4b6e8f2a1c3
Create Date: 2026-07-10

Добавляет:
- task_checklist_items — подзадачи/чек-лист внутри задачи
- tags + task_tags — свободные теги (многие-ко-многим)
- spisok_del.recurrence_rule — правило повторения задачи (none/daily/weekly/monthly)
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d4b6e8f2a1c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Чек-лист внутри задачи ────────────────────────────────────────────────
    op.create_table(
        "task_checklist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("spisok_del.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("is_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_task_checklist_items_task_id", "task_checklist_items", ["task_id"])

    # ── Теги ──────────────────────────────────────────────────────────────────
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("color", sa.String(7), nullable=False, server_default="#6b7280"),
    )
    op.create_table(
        "task_tags",
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("spisok_del.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_task_tags_tag_id", "task_tags", ["tag_id"])

    # ── Повторяющиеся задачи ─────────────────────────────────────────────────
    recurrencerule = postgresql.ENUM(
        "none",
        "daily",
        "weekly",
        "monthly",
        name="recurrencerule",
        create_type=False,
    )
    recurrencerule.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "spisok_del",
        sa.Column(
            "recurrence_rule",
            sa.Enum("none", "daily", "weekly", "monthly", name="recurrencerule"),
            nullable=False,
            server_default="none",
        ),
    )
    # Частичный индекс — быстро найти задачи с активным повторением
    # (подавляющее большинство задач recurrence_rule='none', индексировать их незачем)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_spisok_del_recurrence_active
        ON spisok_del (recurrence_rule)
        WHERE recurrence_rule != 'none'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_spisok_del_recurrence_active")
    op.drop_column("spisok_del", "recurrence_rule")
    op.execute("DROP TYPE IF EXISTS recurrencerule")

    op.drop_index("ix_task_tags_tag_id", table_name="task_tags")
    op.drop_table("task_tags")
    op.drop_table("tags")

    op.drop_index("ix_task_checklist_items_task_id", table_name="task_checklist_items")
    op.drop_table("task_checklist_items")
