# tests/test_admin_setup.py
"""
Smoke-тест для админ-панели (sqladmin). Не проверяет бизнес-логику каждого
ModelView — это отдельная, более объёмная задача — а ловит именно то, что
уже один раз ломало админку целиком: опечатку в импорте (несуществующая
to_local_datetime), которая приводит к ImportError при старте всего
приложения, а не только этой одной вью. Без этого теста такой баг
обнаруживается только руками при заходе в браузер.
"""

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


class TestAdminSetupImports:
    async def test_setup_admin_module_imports_cleanly(self):
        """Ловит ImportError/AttributeError в любой из admin/views/*.py — как было с to_local_datetime."""
        from src.admin.setup import setup_admin  # noqa: F401

    async def test_setup_admin_mounts_without_error(self):
        """setup_admin() реально конструирует все ModelView/BaseView — не только импортирует модуль."""
        from src.admin.setup import setup_admin

        app = FastAPI()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            setup_admin(app, engine)
        finally:
            await engine.dispose()

    async def test_all_admin_view_modules_import(self):
        """Проверяем каждый views/*.py по отдельности — так один общий ImportError в setup.py не маскирует остальные."""
        import importlib
        import pkgutil

        import src.admin.views as views_package

        errors = []
        for module_info in pkgutil.iter_modules(views_package.__path__):
            module_name = f"src.admin.views.{module_info.name}"
            try:
                importlib.import_module(module_name)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{module_name}: {e!r}")

        assert not errors, "Не импортировались: " + "; ".join(errors)


class TestDatetimeFormatters:
    """to_local и to_local_datetime используются в разных вью — фиксируем контракт обеих."""

    async def test_to_local_datetime_handles_none_with_custom_label(self):
        from src.utils.datetime_utils import to_local_datetime

        assert to_local_datetime(None) == "-"
        assert to_local_datetime(None, none_label="Ни разу") == "Ни разу"

    async def test_to_local_datetime_formats_aware_datetime(self):
        from datetime import datetime, timezone

        from src.utils.datetime_utils import to_local_datetime

        dt = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
        result = to_local_datetime(dt)
        assert result != "—"
        assert "2026" in result

    async def test_to_local_still_returns_deadline_specific_label(self):
        """Регресс: to_local (используется для дедлайнов задач) не должен
        был измениться при добавлении to_local_datetime."""
        from src.utils.datetime_utils import to_local

        assert to_local(None) == "Без дедлайна"
