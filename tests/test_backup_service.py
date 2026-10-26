"""Сервис бэкапа БД: скрипт scripts/backup_loop.sh (с подставным pg_dump) и его подключение в docker-compose*.yml."""

import gzip
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "backup_loop.sh"
SH = shutil.which("sh")

needs_sh = pytest.mark.skipif(SH is None, reason="нужен POSIX sh (на Windows — Git Bash/WSL)")

STUB_PG_DUMP = """#!/bin/sh
while [ $# -gt 0 ]; do case "$1" in -f) out="$2"; shift 2;; *) shift;; esac; done
[ "${STUB_FAIL:-0}" = "1" ] && { echo "stub failure" >&2; exit 1; }
[ "${STUB_EMPTY:-0}" = "1" ] && { : > "$out"; exit 0; }
printf 'CREATE TABLE t(id int);\\nINSERT INTO t VALUES (1);\\n' > "$out"
"""
STUB_SLEEP = """#!/bin/sh
echo "$1" > "$SLEEP_LOG"
exit 99
"""


@pytest.fixture
def env(tmp_path):
    """PATH с подставными pg_dump и sleep + каталог для дампов."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("pg_dump", STUB_PG_DUMP), ("sleep", STUB_SLEEP)):
        f = bindir / name
        f.write_text(body, encoding="utf-8")
        f.chmod(0o755)
    out = tmp_path / "backups"
    out.mkdir()
    environ = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "BACKUP_DIR": str(out),
        "PGDATABASE": "testdb",
        "SLEEP_LOG": str(tmp_path / "sleep.log"),
    }
    for var in ("BACKUP_HOUR", "BACKUP_LOCAL_RETENTION_DAYS", "STUB_FAIL", "STUB_EMPTY"):
        environ.pop(var, None)
    return environ, out, tmp_path / "sleep.log"


def _run(environ, *args, **extra):
    return subprocess.run(
        [SH, str(SCRIPT), *args], env={**environ, **extra}, capture_output=True, text=True, timeout=60
    )


def _dumps(out: Path) -> list[Path]:
    return sorted(out.glob("db-*.sql.gz"))


def _make_dump(out: Path, name: str, age_days: float) -> Path:
    f = out / name
    f.write_bytes(gzip.compress(b"-- old"))
    stamp = time.time() - age_days * 86400
    os.utime(f, (stamp, stamp))
    return f


@needs_sh
def test_once_creates_a_valid_gzipped_dump(env):
    environ, out, _ = env
    result = _run(environ, "once")
    assert result.returncode == 0, result.stderr + result.stdout
    (dump,) = _dumps(out)
    assert dump.name.startswith("db-") and dump.name.endswith(".sql.gz")
    assert "CREATE TABLE t" in gzip.decompress(dump.read_bytes()).decode()
    assert not list(out.glob(".db-*")), "временные файлы не должны оставаться"
    assert oct(dump.stat().st_mode & 0o777) == "0o600", "в дампе вся база — читать должен только владелец"


@needs_sh
def test_failed_dump_leaves_nothing_and_fails(env):
    environ, out, _ = env
    result = _run(environ, "once", STUB_FAIL="1")
    assert result.returncode != 0
    assert list(out.iterdir()) == []


@needs_sh
def test_empty_dump_is_not_kept_as_a_backup(env):
    environ, out, _ = env
    result = _run(environ, "once", STUB_EMPTY="1")
    assert result.returncode != 0
    assert list(out.iterdir()) == []


@needs_sh
def test_old_dumps_are_pruned_but_three_newest_always_stay(env):
    environ, out, _ = env
    for i in range(5):  # все старше 7 дней
        _make_dump(out, f"db-2026-01-0{i + 1}_03-00-00.sql.gz", age_days=10 + i)
    result = _run(environ, "once", BACKUP_LOCAL_RETENTION_DAYS="7")
    assert result.returncode == 0, result.stderr
    names = [p.name for p in _dumps(out)]
    assert len(names) == 3, names  # свежий дамп + два самых новых из старых
    assert "db-2026-01-01_03-00-00.sql.gz" in names and "db-2026-01-02_03-00-00.sql.gz" in names


@needs_sh
def test_recent_dumps_are_never_pruned(env):
    environ, out, _ = env
    for i in range(6):
        _make_dump(out, f"db-2026-02-0{i + 1}_03-00-00.sql.gz", age_days=i * 0.5)
    result = _run(environ, "once", BACKUP_LOCAL_RETENTION_DAYS="7")
    assert result.returncode == 0
    assert len(_dumps(out)) == 7  # 6 прежних + новый


@needs_sh
def test_pruning_ignores_foreign_files(env):
    environ, out, _ = env
    foreign = out / "notes.txt"
    foreign.write_text("не дамп", encoding="utf-8")
    os.utime(foreign, (0, 0))
    _run(environ, "once", BACKUP_LOCAL_RETENTION_DAYS="1")
    assert foreign.exists()


@needs_sh
@pytest.mark.parametrize(
    "name,value", [("BACKUP_HOUR", "25"), ("BACKUP_HOUR", "abc"), ("BACKUP_LOCAL_RETENTION_DAYS", "-1")]
)
def test_bad_settings_fail_fast(env, name, value):
    environ, out, _ = env
    result = _run(environ, "once", **{name: value})
    assert result.returncode == 2 and name in result.stdout
    assert list(out.iterdir()) == []


@needs_sh
def test_loop_takes_first_dump_immediately_then_sleeps_until_next_run(env):
    environ, out, sleep_log = env
    result = _run(environ)  # подставной sleep завершает скрипт кодом 99
    assert result.returncode == 99, result.stderr + result.stdout
    assert len(_dumps(out)) == 1, "первый дамп — сразу при запуске, а не через сутки"
    wait = int(sleep_log.read_text().strip())
    assert 0 < wait <= 86400
    assert "следующий дамп через" in result.stdout


@needs_sh
def test_loop_skips_immediate_dump_when_a_recent_one_exists(env):
    environ, out, sleep_log = env
    existing = _make_dump(out, "db-2026-03-01_03-00-00.sql.gz", age_days=0.1)
    result = _run(environ)
    assert result.returncode == 99
    assert _dumps(out) == [existing]
    assert sleep_log.exists()


@needs_sh
def test_loop_retries_failed_first_dump(env):
    environ, out, sleep_log = env
    result = _run(environ, STUB_FAIL="1")
    assert result.returncode == 99  # sleep 600 перед повтором — подставной sleep прерывает
    assert sleep_log.read_text().strip() == "600"
    assert "повтор через 10 минут" in result.stdout
    assert list(out.iterdir()) == []


# ── подключение в compose ────────────────────────────────────────────────────
def _services(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))["services"]


def test_backup_runs_by_default_without_a_profile():
    backup = _services("docker-compose.yml")["backup"]
    assert "profiles" not in backup, "бэкап должен подниматься обычным `docker compose up`"
    assert backup["image"].startswith("postgres:16"), "pg_dump должен совпадать по версии с сервером postgres"
    assert _services("docker-compose.yml")["postgres"]["image"].startswith("postgres:16")
    assert backup["restart"] == "unless-stopped"
    assert backup["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_backup_writes_to_the_same_host_dir_the_host_script_and_r2_upload_use():
    volumes = _services("docker-compose.yml")["backup"]["volumes"]
    assert "./backups:/backups" in volumes
    assert any(v.startswith("./scripts/backup_loop.sh:") and v.endswith(":ro") for v in volumes)
    assert "./backups:/app/backups" in _services("docker-compose.prod.yml")["app"]["volumes"]


def test_backup_entrypoint_runs_the_script_and_strips_crlf():
    entry = _services("docker-compose.yml")["backup"]["entrypoint"]
    assert entry[:2] == ["/bin/sh", "-c"]
    command = entry[2]
    assert "backup_loop.sh" in command and "tr -d '\\r'" in command, "CRLF от git на Windows ломает sh"
    assert '"$$@"' in command, "аргументы (`once`) должны доходить до скрипта; $$ — экранирование compose"


def test_backup_has_a_healthcheck_that_notices_missing_dumps():
    check = _services("docker-compose.yml")["backup"]["healthcheck"]
    assert "db-*.sql.gz" in " ".join(check["test"]) and "-mmin" in " ".join(check["test"])


def test_prod_backup_requires_postgres_credentials_and_restarts_always():
    backup = _services("docker-compose.prod.yml")["backup"]
    assert backup["restart"] == "always"
    for var in ("PGUSER", "PGPASSWORD", "PGDATABASE"):
        assert ":?" in backup["environment"][var], f"{var}: прод не должен молча брать дев-значения"


def test_backup_settings_are_documented_in_the_prod_env_example():
    text = (ROOT / ".env.prod.example").read_text(encoding="utf-8")
    assert "BACKUP_HOUR=" in text and "BACKUP_LOCAL_RETENTION_DAYS=" in text


def test_shell_scripts_keep_lf_line_endings():
    assert "*.sh text eol=lf" in (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert b"\r" not in SCRIPT.read_bytes()
