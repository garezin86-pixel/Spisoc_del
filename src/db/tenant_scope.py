# src/db/tenant_scope.py
"""Автоматическое проставление workspace_id новым строкам.

Проблема, которую это решает: TenantMixin.workspace_id теперь NOT NULL на
всех 12 tenant-таблицах в Postgres (см. миграцию e4f5a6b7c8d9), но сами
конструкторы — SpisokModel(...), ProjectModel(...), GroupModel(...) и т.д. —
разбросаны по полутора десяткам файлов сервисов/бота и исторически никогда
не задавали workspace_id явно. Патчить каждый вызов конструктора вручную —
долго и ненадёжно: забыть один — значит сломать именно его при первом же
создании записи в реальном Postgres (тесты на SQLite это не ловят, пока
сама модель тоже не NOT NULL, см. ниже).

Вместо этого: один раз говорим сессии, в каком она workspace (см.
set_session_workspace), а слушатель SQLAlchemy "before_flush" сам
проставляет workspace_id любому новому объекту с TenantMixin, у которого
оно ещё не задано явно. Если вызывающий код сам передал workspace_id в
конструктор — слушатель его не трогает (это нужно для редких случаев,
когда одна операция намеренно пишет в другой workspace, например при
принятии приглашения).

Это закрывает ТОЛЬКО запись (INSERT). Чтение (SELECT) всё ещё не
фильтруется по workspace автоматически — это отдельная, ещё не сделанная
часть (do_orm_execute + with_loader_criteria, см. обсуждение мультитенантности
в истории задачи). Сервисы по-прежнему обязаны сами фильтровать выборки по
workspace_id, иначе один пользователь может прочитать чужие данные по id.
"""

import threading

from sqlalchemy import event
from sqlalchemy.orm import Session

from src.models.mixins import TenantMixin

_INSTALLED = False

# Только для тестов: десятки тестовых файлов создают свой собственный
# async_sessionmaker(engine, ...) напрямую (не через src.db.get_session_maker),
# и патчить каждый такой вызов, чтобы передать info={"workspace_id": ...},
# пришлось бы в 25+ файлах. Вместо этого тестовый autouse-фикстур в
# tests/conftest.py один раз на тест кладёт сюда id тестового workspace, а
# _autofill_workspace_id (ниже) подхватывает его как запасной вариант для
# ЛЮБОЙ сессии, у которой session.info["workspace_id"] не задан явно —
# независимо от того, через какой sessionmaker она создана.
#
# Простая переменная уровня модуля, а не contextvars.ContextVar и не
# слушатель события Session "init": оба варианта проверялись и не подошли —
# "init" у Session эмпирически не срабатывает для AsyncSession (её
# конструктор не создаёт внутреннюю sync-сессию сразу), а contextvars не
# распространяется между отдельными asyncio Task, в которых pytest-asyncio
# выполняет async-фикстуру и тело самого теста. pytest по умолчанию гоняет
# тесты последовательно в одном процессе, поэтому простая переменная
# безопасна. В проде не используется — workspace туда приходит только из
# set_session_workspace().
_test_default_workspace_id: int | None = None
_test_default_lock = threading.Lock()


def _set_test_default_workspace(workspace_id: int | None) -> None:
    global _test_default_workspace_id
    with _test_default_lock:
        _test_default_workspace_id = workspace_id


def set_session_workspace(session: Session, workspace_id: int | None) -> None:
    """Привязывает сессию к workspace — вызывайте один раз на запрос/задачу,
    как можно раньше (см. src/core/dependencies.py:get_current_user).

    workspace_id=None осознанно допустим: это платформенный режим (вы,
    is_platform_admin, SQLAdmin, фоновые задачи без привязки к одной
    компании) — такие сессии просто не получают автозаполнение и обязаны
    проставлять workspace_id сами там, где это нужно.
    """
    session.info["workspace_id"] = workspace_id


def _autofill_workspace_id(session: Session, _flush_context, _instances) -> None:
    workspace_id = session.info.get("workspace_id")
    if workspace_id is None:
        # В проде это всегда None (глобальная переменная ниже заполняется
        # только тестовой фикстурой) — тогда просто ничего не делаем, как и
        # раньше: NOT NULL на БД — настоящая защита для прода.
        workspace_id = _test_default_workspace_id
    if workspace_id is None:
        return
    for obj in session.new:
        if isinstance(obj, TenantMixin) and obj.workspace_id is None:
            obj.workspace_id = workspace_id


def install_tenant_autofill() -> None:
    """Регистрирует слушатель один раз за процесс (idempotent)."""
    global _INSTALLED
    if _INSTALLED:
        return
    event.listen(Session, "before_flush", _autofill_workspace_id)
    _INSTALLED = True


# Вызывается при первом импорте этого модуля — то есть при первом же
# session_maker() в src/db/__init__.py (используется и веб-приложением, и
# ботом, и планировщиком). Явный вызов install_tenant_autofill() из
# src/main.py не нужен: event.listen на классе Session не привязан к
# конкретному приложению/процессу, достаточно, чтобы он сработал один раз.
install_tenant_autofill()
