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

Чтение (SELECT) и UPDATE/DELETE фильтруются слушателем "do_orm_execute"
(_scope_orm_execute ниже): если у сессии задан workspace_id, к КАЖДОМУ
ORM-запросу автоматически добавляется `workspace_id = :ws` для всех
моделей с TenantMixin (with_loader_criteria, включая алиасы, JOIN-ы и
ленивые загрузки связей). Сервисам не нужно фильтровать вручную.

Важные границы (читать перед тем, как на это полагаться):
  * Fail-open: если workspace не определён ни в session.info, ни в
    контексте (см. workspace_context ниже) — фильтра нет. Так работают
    логин, планировщик, SQLAdmin и сам get_current_user (он загружает
    пользователя ДО того, как узнает его workspace). Telegram-бот
    привязывается автоматически: WorkspaceContextMiddleware на каждый
    апдейт кладёт workspace пользователя в контекст, и ВСЕ сессии,
    открытые внутри обработчика (включая фоновые задачи, порождённые им
    через asyncio.create_task), фильтруются и автозаполняются.
  * Не покрывается: сырой text(), чистый Core (select(table.c.x) без ORM-
    сущности) и session.get() для объекта, который уже лежит в identity
    map этой же сессии (SQL не выполняется).
  * Тестовый запасной workspace (_test_default_workspace_id) на чтение НЕ
    влияет — только на запись, иначе существующие тесты, создающие данные
    в нескольких workspace, начали бы получать пустые выборки.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from src.models.mixins import TenantMixin

_INSTALLED = False

# Запрос с .execution_options(skip_workspace_scope=True) читает ВСЕ компании.
# Только для идентификаторов, которые по замыслу уникальны глобально и нужны
# для входа/проверки уникальности (login) — не для пользовательских данных.
SKIP_WORKSPACE_SCOPE = "skip_workspace_scope"

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


# Workspace «текущей задачи asyncio» — для кода, который открывает сессии сам
# (Telegram-бот: десятки хендлеров делают `UnitOfWork(get_session_maker())`
# и не имеют общего места, где можно вызвать set_session_workspace).
# В отличие от тестовой переменной выше это именно ContextVar: каждый апдейт
# бота обрабатывается в своей задаче, а дочерние задачи (create_task) получают
# копию контекста — фоновая загрузка вложений и уведомления остаются
# привязанными к компании, из чьего апдейта их запустили.
_current_workspace: ContextVar[int | None] = ContextVar("current_workspace_id", default=None)


@contextmanager
def workspace_context(workspace_id: int | None) -> Iterator[None]:
    """Все сессии, открытые внутри блока, привязаны к workspace_id.

    Явно заданный session.info["workspace_id"] приоритетнее контекста.
    workspace_id=None — ничего не привязывает (платформенный режим).
    """
    token = _current_workspace.set(workspace_id)
    try:
        yield
    finally:
        _current_workspace.reset(token)


def current_workspace_id() -> int | None:
    """Workspace текущего контекста (бот, фоновые задачи из его хендлеров) или None."""
    return _current_workspace.get()


def _effective_workspace(session: Session) -> int | None:
    return session.info.get("workspace_id") or _current_workspace.get()


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
    workspace_id = _effective_workspace(session)
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


def _scope_orm_execute(state: ORMExecuteState) -> None:
    """Добавляет фильтр по workspace к любому ORM-запросу сессии."""
    if state.is_column_load:
        # Подгрузка отложенных колонок объекта, который уже прошёл фильтр.
        return
    if state.execution_options.get(SKIP_WORKSPACE_SCOPE):
        return
    workspace_id = _effective_workspace(state.session)
    if workspace_id is None:
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.workspace_id == workspace_id,
            include_aliases=True,
        )
    )


def install_tenant_autofill() -> None:
    """Регистрирует слушатели (запись и чтение) один раз за процесс (idempotent)."""
    global _INSTALLED
    if _INSTALLED:
        return
    event.listen(Session, "before_flush", _autofill_workspace_id)
    event.listen(Session, "do_orm_execute", _scope_orm_execute)
    _INSTALLED = True


# Вызывается при первом импорте этого модуля — то есть при первом же
# session_maker() в src/db/__init__.py (используется и веб-приложением, и
# ботом, и планировщиком). Явный вызов install_tenant_autofill() из
# src/main.py не нужен: event.listen на классе Session не привязан к
# конкретному приложению/процессу, достаточно, чтобы он сработал один раз.
install_tenant_autofill()
