"""Инструкция по установке не должна расходиться с проектом: переменные, файлы и команды из INSTALL.md существуют."""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
INSTALL = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
ENV_PROD = (ROOT / ".env.prod.example").read_text(encoding="utf-8")
PROD = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
BASE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def _backticked(text: str) -> set[str]:
    return set(re.findall(r"`([^`\n]+)`", text))


def test_every_variable_compose_requires_is_documented_and_present_in_the_example():
    required = set(re.findall(r"\$\{([A-Z_]+):\?", PROD + BASE))
    assert {"POSTGRES_PASSWORD", "GRAFANA_ADMIN_PASSWORD"} <= required
    for name in sorted(required):
        assert f"{name}=" in ENV_PROD, f"{name} обязателен для compose, но его нет в .env.prod.example"
        if name in ("POSTGRES_USER", "POSTGRES_DB"):  # в инструкции сказано, что их можно оставить как в примере
            continue
        assert name in INSTALL, f"{name} обязателен для запуска, но не описан в docs/INSTALL.md"


def test_secrets_the_app_refuses_to_start_without_are_documented():
    for name in ("SECRET_KEY", "REFRESH_SECRET_KEY", "ADMIN_SECRET_KEY"):
        assert name in INSTALL and f"{name}=" in ENV_PROD


def test_documented_variables_exist_somewhere_in_the_project():
    known = ENV_PROD + (ROOT / "frontend" / ".env.example").read_text(encoding="utf-8") + PROD + BASE
    ignored = {"DC", "APP_BIND_", "ENV"}
    for token in _backticked(INSTALL):
        for name in re.findall(r"\b([A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+)\b", token):
            if name in ignored or name.startswith("REPLACE"):
                continue
            assert name in known, f"в docs/INSTALL.md упомянута переменная {name}, которой нет в проекте"


def test_files_and_commands_mentioned_in_the_install_guide_exist():
    for token in _backticked(INSTALL):
        for path in re.findall(r"\b((?:docs|scripts|deploy|frontend)/[\w./-]+\.\w+)\b", token):
            assert (ROOT / path).exists(), f"docs/INSTALL.md ссылается на {path}, а такого файла нет"
    assert (ROOT / ".env.prod.example").exists() and (ROOT / "frontend" / ".env.example").exists()
    assert (ROOT / "scripts" / "init_instance.py").exists() and "python -m scripts.init_instance" in INSTALL
    assert "backup once" in INSTALL and (ROOT / "docs" / "backup-and-restore.md").exists()


def test_compose_commands_in_the_guide_use_both_files_and_env_file():
    assert "--env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml" in INSTALL


def test_without_telegram_command_lists_only_services_that_exist():
    services = set(yaml.safe_load(BASE)["services"])
    line = next(ln for ln in INSTALL.splitlines() if "up -d --build app" in ln)
    names = line.split("--build")[1].split()
    assert names and set(names) <= services and "bot" not in names


# ── HTTPS-профиль (Caddy) ────────────────────────────────────────────────────
def test_caddy_is_an_optional_profile_with_standard_ports():
    caddy = yaml.safe_load(PROD)["services"]["caddy"]
    assert caddy["profiles"] == ["https"], "без профиля Caddy не должен стартовать"
    assert {"80:80", "443:443"} <= set(caddy["ports"])
    assert "./deploy/Caddyfile:/etc/caddy/Caddyfile:ro" in caddy["volumes"]
    assert caddy["depends_on"]["app"]["condition"] == "service_started"
    assert set(yaml.safe_load(PROD)["volumes"]) >= {"caddy_data", "caddy_config"}


def test_caddy_does_not_make_domain_mandatory_for_a_plain_prod_start():
    """`${DOMAIN:?}` сломал бы обычный запуск без HTTPS: compose подставляет переменные и для неактивных профилей."""
    caddy = yaml.safe_load(PROD)["services"]["caddy"]  # разбираем YAML: комментарии с пояснением сюда не попадают
    assert caddy["environment"]["DOMAIN"] == "${DOMAIN:-}"
    command = " ".join(caddy["command"])
    assert 'test -n "$$DOMAIN"' in command and "exit 1" in command


def test_caddyfile_proxies_the_domain_to_the_app():
    text = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "{$DOMAIN}" in text and "reverse_proxy app:8000" in text


def test_https_setup_keeps_forwarded_ips_wildcard_tied_to_loopback_bind():
    """`FORWARDED_ALLOW_IPS=*` допустимо только когда порт приложения закрыт от внешней сети."""
    section = INSTALL[INSTALL.index("## 7. HTTPS") : INSTALL.index("## 8.")]
    assert "APP_BIND=127.0.0.1" in section and "FORWARDED_ALLOW_IPS=*" in section
    assert "без `APP_BIND` его включать нельзя" in section
    assert "${APP_BIND:-0.0.0.0}:8000:8000" in BASE
    for name in ("DOMAIN", "APP_BIND"):
        assert name in ENV_PROD


def test_https_profile_command_in_guide_uses_the_profile_flag():
    assert "--profile https up -d" in INSTALL
