# Миграция для filter_presets

Не подставляю руками revision id/down_revision — они зависят от вашей текущей
цепочки миграций. Просто сгенерируйте автоматически:

```bash
alembic revision --autogenerate -m "add filter_presets table"
```

## Важный нюанс: переиспользование ENUM taskstatus/taskpriority

`FilterPresetModel.status`/`priority` используют `SAEnum(TaskStatus, name="taskstatus")`
и `SAEnum(TaskPriority, name="taskpriority")` — ТЕ ЖЕ САМЫЕ типы Postgres ENUM,
что уже созданы для таблицы `spisok_del`. Проверьте автосгенерированный файл:

- Alembic/SQLAlchemy обычно достаточно умны и НЕ будут пытаться создать тип
  заново (checkfirst), но иногда в autogenerate всё равно попадает
  `sa.Enum(..., name='taskstatus').create(op.get_bind(), checkfirst=True)`
  прямо перед `op.create_table(...)` — если увидите такое, убедитесь, что
  стоит `checkfirst=True` (обычно стоит по умолчанию), иначе миграция упадёт
  с "type taskstatus already exists" при повторном запуске на чистой базе,
  где spisok_del создаётся в той же транзакции.
- Если увидите ДВА отдельных `CREATE TYPE taskstatus`/`taskpriority` в одной
  миграции (маловероятно, но бывает при ручных правках) — уберите второй,
  оставьте только `op.create_table(...)` с `sa.Enum(..., name='taskstatus')`
  без `.create()`.

## Пример ожидаемого содержимого upgrade()

```python
def upgrade() -> None:
    op.create_table(
        "filter_presets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.Enum("backlog", "todo", "in_progress", "review", "done", name="taskstatus"), nullable=True),
        sa.Column("priority", sa.Enum("low", "medium", "high", "critical", name="taskpriority"), nullable=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filter_user_group", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_filter_preset_user_name"),
    )


def downgrade() -> None:
    op.drop_table("filter_presets")
```
