"""Первый запуск: компания + администратор + воронка из консоли (scripts/init_instance.py)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.tenant_scope import SKIP_WORKSPACE_SCOPE
from src.models.deal import PipelineModel
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel
from src.schemas.deal import StageKind
from src.services.instance_setup_service import (
    AlreadyInitialized,
    SetupError,
    generate_password,
    is_initialized,
    parse_stages,
    setup_instance,
)


@pytest.fixture
def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _count(maker, model) -> int:
    async with maker() as s:
        return await s.scalar(select(func.count()).select_from(model).execution_options(**{SKIP_WORKSPACE_SCOPE: True}))


# ── чистые функции ───────────────────────────────────────────────────────────
def test_default_stages_when_nothing_given():
    names = [n for n, _ in parse_stages(None)]
    assert names[0] == "Новая" and names[-2:] == ["Успех", "Отказ"]
    assert parse_stages("") == parse_stages(None) == parse_stages([])


def test_custom_stages_are_open_and_closing_ones_added_last():
    spec = parse_stages("Лид, Переговоры; КП\nДоговор")
    assert [n for n, _ in spec] == ["Лид", "Переговоры", "КП", "Договор", "Успех", "Отказ"]
    assert [k for _, k in spec] == [StageKind.open] * 4 + [StageKind.won, StageKind.lost]


def test_duplicates_and_closing_names_in_input_are_dropped():
    spec = parse_stages("Лид, лид, Успех, ОТКАЗ, Договор")
    assert [n for n, _ in spec] == ["Лид", "Договор", "Успех", "Отказ"]


def test_only_closing_stages_is_an_error():
    with pytest.raises(SetupError, match="ни одной стадии"):
        parse_stages("Успех, Отказ")


def test_too_many_stages_is_an_error():
    with pytest.raises(SetupError, match="Слишком много"):
        parse_stages([f"Стадия {i}" for i in range(21)])


def test_generated_password_is_strong_and_readable():
    passwords = {generate_password() for _ in range(50)}
    assert len(passwords) == 50
    for p in passwords:
        assert len(p) == 16 and not set(p) & set("0O1lI")
        assert any(c.islower() for c in p) and any(c.isupper() for c in p) and any(c.isdigit() for c in p)


# ── настройка установки ──────────────────────────────────────────────────────
async def test_setup_creates_company_admin_and_pipeline_and_admin_can_log_in(client, maker):
    async with maker() as s:
        assert not await is_initialized(s)
        result = await setup_instance(
            s,
            company_name="ООО Ромашка",
            admin_username="boss",
            admin_password="Str0ng-pass",
            stages="Лид, Переговоры, Договор",
        )
    assert not result.password_generated and result.password == "Str0ng-pass"
    assert result.stages == ["Лид", "Переговоры", "Договор", "Успех", "Отказ"]

    async with maker() as s:
        assert await is_initialized(s)
        admin = (await s.execute(select(UserModel).where(UserModel.id == result.admin_id))).scalar_one()
        assert admin.role == "admin" and admin.workspace_id == result.workspace_id and not admin.must_change_password
        workspace = (
            await s.execute(select(WorkspaceModel).where(WorkspaceModel.id == result.workspace_id))
        ).scalar_one()
        assert workspace.name == "ООО Ромашка" and workspace.slug == "ooo-romashka"

    login = await client.post("/auth/login", json={"username": result.login, "password": "Str0ng-pass"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    pipelines = (await client.get("/api/pipelines", headers=headers)).json()
    assert len(pipelines) == 1 and pipelines[0]["name"] == "Продажи"
    assert [s["name"] for s in pipelines[0]["stages"]] == result.stages
    assert [s["kind"] for s in pipelines[0]["stages"]][-2:] == ["won", "lost"]


async def test_generated_password_works_and_must_be_changed(client, maker):
    async with maker() as s:
        result = await setup_instance(s, company_name="Моя Компания", admin_username="admin")
    assert result.password_generated and len(result.password) == 16
    login = await client.post("/auth/login", json={"username": result.login, "password": result.password})
    assert login.status_code == 200, login.text
    assert login.json()["must_change_password"] is True


async def test_setup_twice_changes_nothing(maker):
    async with maker() as s:
        await setup_instance(s, company_name="Первая", admin_username="first", admin_password="Str0ng-pass")
    users_before, pipelines_before = await _count(maker, UserModel), await _count(maker, PipelineModel)
    async with maker() as s:
        with pytest.raises(AlreadyInitialized):
            await setup_instance(s, company_name="Вторая", admin_username="second", admin_password="Str0ng-pass")
    assert await _count(maker, UserModel) == users_before
    assert await _count(maker, PipelineModel) == pipelines_before


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"admin_password": "short"}, "не короче 8"),
        ({"company_name": "A"}, "company_name"),
        ({"admin_username": "x"}, "username"),
        ({"stages": "Успех"}, "ни одной стадии"),
    ],
)
async def test_bad_input_is_rejected_and_nothing_is_created(maker, kwargs, message):
    params = {"company_name": "Компания", "admin_username": "admin", "admin_password": "Str0ng-pass", **kwargs}
    async with maker() as s:
        with pytest.raises(SetupError, match=message):
            await setup_instance(s, **params)
    assert await _count(maker, UserModel) == 0 and await _count(maker, PipelineModel) == 0


async def test_setup_works_when_another_company_row_exists_but_no_users(maker):
    """В тестах (и после неудачной попытки) в базе может быть пустая компания: пользователей нет — настраиваем."""
    async with maker() as s:
        result = await setup_instance(s, company_name="Новая", admin_username="admin", admin_password="Str0ng-pass")
    assert result.workspace_id


# ── консольный скрипт ────────────────────────────────────────────────────────
def _args(**kwargs):
    import argparse

    return argparse.Namespace(**{"company": None, "admin": None, "stages": None, "demo": False, **kwargs})


@pytest.fixture
def cli(maker, monkeypatch):
    """scripts/init_instance.py, подключённый к тестовой БД; переменные INIT_* сброшены."""
    from scripts import init_instance

    monkeypatch.setattr(init_instance, "get_session_maker", lambda: maker)
    for name in ("INIT_COMPANY_NAME", "INIT_ADMIN_USERNAME", "INIT_ADMIN_PASSWORD", "INIT_STAGES", "INIT_DEMO"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    return init_instance


async def test_cli_creates_instance_prints_login_and_generated_password_once(cli, capsys, maker):
    code = await cli.run(_args(company="ООО Лотос", admin="boss", stages="Лид, Договор"))
    out = capsys.readouterr().out
    assert code == 0
    assert "Логин для входа: boss" in out and "сохраните сейчас" in out and "Лид → Договор → Успех → Отказ" in out
    assert await _count(maker, UserModel) == 1


async def test_cli_uses_environment_without_dialog(cli, capsys, monkeypatch, client):
    monkeypatch.setenv("INIT_COMPANY_NAME", "Моя Компания")
    monkeypatch.setenv("INIT_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("INIT_ADMIN_PASSWORD", "Str0ng-pass")
    assert await cli.run(_args()) == 0
    out = capsys.readouterr().out
    assert "тот, что вы задали" in out and "Str0ng-pass" not in out, "заданный пароль не печатаем"
    assert (await client.post("/auth/login", json={"username": "owner", "password": "Str0ng-pass"})).status_code == 200


async def test_cli_second_run_is_harmless(cli, capsys, maker):
    assert await cli.run(_args(company="Первая", admin="first")) == 0
    capsys.readouterr()
    assert await cli.run(_args(company="Вторая", admin="second")) == 0
    assert "уже настроена" in capsys.readouterr().out
    assert await _count(maker, UserModel) == 1


async def test_cli_without_data_and_without_terminal_fails_with_hint(cli, capsys, maker):
    assert await cli.run(_args()) == 1
    assert "--company" in capsys.readouterr().err
    assert await _count(maker, UserModel) == 0


async def test_cli_reports_bad_data_with_exit_code_1(cli, capsys, monkeypatch):
    monkeypatch.setenv("INIT_ADMIN_PASSWORD", "123")
    assert await cli.run(_args(company="Компания", admin="admin")) == 1
    assert "не короче 8" in capsys.readouterr().err


async def test_cli_database_not_ready_exit_code_2(cli, capsys, monkeypatch):
    from sqlalchemy.exc import OperationalError

    async def broken(*args, **kwargs):
        raise OperationalError("select 1", {}, Exception("connection refused"))

    monkeypatch.setattr(cli, "setup_instance", broken)
    assert await cli.run(_args(company="Компания", admin="admin")) == 2
    assert "docker compose up -d" in capsys.readouterr().err


async def test_cli_interactive_dialog_generates_password_on_enter(cli, capsys, monkeypatch, maker):
    answers = iter(["Диалог ООО", "dialog_admin", "", ""])  # компания, админ, стадии и демо (Enter — по умолчанию)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "")  # пароль: Enter — сгенерировать
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    assert await cli.run(_args()) == 0
    out = capsys.readouterr().out
    assert "Логин для входа: dialogadmin" in out and "Новая → Связались" in out


async def test_cli_demo_flag_loads_demo_data_into_the_new_company(cli, capsys, maker):
    from src.models.client import ClientModel

    assert await cli.run(_args(company="Демо Компания", admin="boss", demo=True)) == 0
    out = capsys.readouterr().out
    assert "Демо-данные:     12 клиентов, 8 сделок, 6 задач" in out
    assert await _count(maker, ClientModel) == 12


async def test_cli_demo_from_environment_and_not_by_default(cli, capsys, maker, monkeypatch):
    from src.models.client import ClientModel

    assert await cli.run(_args(company="Без демо", admin="boss")) == 0
    assert "Демо-данные" not in capsys.readouterr().out and await _count(maker, ClientModel) == 0


async def test_cli_demo_env_switch(cli, capsys, maker, monkeypatch):
    from src.models.client import ClientModel

    monkeypatch.setenv("INIT_DEMO", "1")
    assert await cli.run(_args(company="Демо через env", admin="boss")) == 0
    assert await _count(maker, ClientModel) == 12
