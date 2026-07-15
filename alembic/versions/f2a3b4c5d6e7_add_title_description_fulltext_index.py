"""add combined title+description fulltext index

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-10

Существующий индекс ix_spisok_del_title_gin (миграция a9f3b2c1d8e7) покрывает
только title. Этот индекс добавляет полнотекстовый поиск по title+description
вместе — используется в TaskRepository.search_tasks_fulltext().

Оставляем старый индекс как есть (не удаляем) — он не мешает, а полное
удаление/пересоздание было бы лишним риском на проде без явной необходимости.
"""

from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_spisok_del_title_description_gin
        ON spisok_del
        USING gin(
            to_tsvector('russian', coalesce(title, '') || ' ' || coalesce(description, ''))
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_spisok_del_title_description_gin")
