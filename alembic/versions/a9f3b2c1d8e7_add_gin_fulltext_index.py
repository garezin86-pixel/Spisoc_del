"""add gin fulltext index on tasks title

Revision ID: a9f3b2c1d8e7
Revises: f1a59d8d63c6
Create Date: 2026-06-07 12:00:00.000000

"""

from typing import Sequence, Union
from alembic import op

revision: str = "a9f3b2c1d8e7"
down_revision: Union[str, Sequence[str], None] = "f1a59d8d63c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Включаем расширение для русского языка (если не включено)
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    # GIN-индекс по title — поддерживает русский и английский
    # CONCURRENTLY не работает внутри транзакции, поэтому используем обычный CREATE
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_spisok_del_title_gin
        ON spisok_del
        USING gin(to_tsvector('russian', coalesce(title, '')))
    """)

    # Дополнительно — trigram индекс для поиска по подстроке (ILIKE)
    # Нужен если хочется оставить возможность поиска частичного слова
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_spisok_del_title_trgm
        ON spisok_del
        USING gin(title gin_trgm_ops)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_spisok_del_title_gin")
    op.execute("DROP INDEX IF EXISTS ix_spisok_del_title_trgm")
