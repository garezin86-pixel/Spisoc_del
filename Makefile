.PHONY: run dev test lint format migrate downgrade bot help

# ── Запуск ────────────────────────────────────────────────────────────────────
run:
	uvicorn src.main:app --host 0.0.0.0 --port 8000

dev:
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

bot:
	python -m src.bot.runner

# ── Тесты ─────────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --tb=short --cov=src --cov-report=term-missing --cov-report=html

# ── Линтинг ───────────────────────────────────────────────────────────────────
lint:
	ruff check src tests

format:
	ruff format src tests
	ruff check src tests --fix

# ── Миграции ──────────────────────────────────────────────────────────────────
migrate:
	alembic upgrade head

downgrade:
	alembic downgrade -1

migration:
	@read -p "Migration name: " name; \
	alembic revision --autogenerate -m "$$name"

# ── Помощь ────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  make dev        — запуск с hot-reload"
	@echo "  make run        — запуск без hot-reload (prod)"
	@echo "  make bot        — запуск Telegram бота"
	@echo "  make test       — запуск тестов"
	@echo "  make test-cov   — тесты с покрытием"
	@echo "  make lint       — проверка стиля (ruff)"
	@echo "  make format     — автоформатирование"
	@echo "  make migrate    — применить миграции"
	@echo "  make downgrade  — откатить последнюю миграцию"
	@echo "  make migration  — создать новую миграцию"
	@echo ""
