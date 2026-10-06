"""Статическая проверка docker-compose*.yml: служебные порты не торчат наружу, команды запуска корректны."""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
INTERNAL = ("postgres", "redis", "prometheus", "grafana")  # служебные сервисы: только loopback


def _load(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))["services"]


def _effective_ports(service: str, *files: str) -> list[str]:
    """Как Compose сливает несколько файлов: списки `ports` СКЛАДЫВАЮТСЯ, пустой список ничего не убирает
    (проверено вживую: base с 5432:5432 + override с `ports: []` даёт опубликованный 5432)."""
    ports: list[str] = []
    for f in files:
        ports += [str(p) for p in (_load(f).get(service, {}).get("ports") or [])]
    return ports


@pytest.mark.parametrize("files", [("docker-compose.yml",), ("docker-compose.yml", "docker-compose.prod.yml")])
@pytest.mark.parametrize("service", INTERNAL)
def test_internal_services_publish_ports_on_loopback_only(service, files):
    for mapping in _effective_ports(service, *files):
        assert mapping.startswith("127.0.0.1:"), (
            f"{service}: порт {mapping!r} слушает все интерфейсы. Не рассчитывайте на `ports: []` в override-файле — "
            "он порты базового файла не убирает; привязывайте к 127.0.0.1 прямо в docker-compose.yml."
        )


def test_application_port_is_still_published():
    assert "8000:8000" in _effective_ports("app", "docker-compose.yml", "docker-compose.prod.yml")


def test_prod_file_does_not_pretend_to_close_ports_with_empty_list():
    """`ports: []` создаёт ложное чувство безопасности — это no-op, см. _effective_ports."""
    text = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert not re.search(r"^\s+ports:\s*\[\s*\]", text, flags=re.M)


def _uvicorn_targets() -> list[tuple[str, str]]:
    found = []
    for name in ("docker-compose.yml", "docker-compose.dev.yml", "docker-compose.prod.yml"):
        for svc, conf in _load(name).items():
            cmd = conf.get("command")
            if isinstance(cmd, str) and "uvicorn" in cmd:
                found.append((f"{name}:{svc}", cmd))
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    found += [("Dockerfile", m) for m in re.findall(r"uvicorn\s.*", dockerfile)]
    return found


def test_uvicorn_app_import_strings_are_valid():
    """Раньше в docker-compose.dev.yml было `src/main:app` — uvicorn не может импортировать такой модуль."""
    targets = _uvicorn_targets()
    assert len(targets) >= 3  # base + dev + Dockerfile: тест не должен молча ничего не проверять
    for where, cmd in targets:
        match = re.search(r"uvicorn\s+([^\s]+)", cmd)
        assert match, f"{where}: не нашёл цель uvicorn в {cmd!r}"
        assert re.fullmatch(r"[A-Za-z_][\w.]*:[A-Za-z_]\w*", match.group(1)), f"{where}: плохая цель {match.group(1)!r}"
