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
echo "pg_dump $*" >> "${CALL_LOG:-/dev/null}"
while [ $# -gt 0 ]; do case "$1" in -f) out="$2"; shift 2;; *) shift;; esac; done
[ "${STUB_FAIL:-0}" = "1" ] && { echo "stub failure" >&2; exit 1; }
[ "${STUB_EMPTY:-0}" = "1" ] && { : > "$out"; exit 0; }
printf 'CREATE TABLE t(id int);\\nINSERT INTO t VALUES (1);\\n' > "$out"
"""
STUB_PSQL = """#!/bin/sh
echo "psql $*" >> "${CALL_LOG:-/dev/null}"
case "$*" in
  *to_regclass*) echo t ;;
  *"count(*)"*) echo 7 ;;
  *alembic_version*) echo n9c0d1e2f3a4 ;;
  *DROP*) [ "${PSQL_FAIL_DROP:-0}" = "1" ] && exit 1; : ;;
  *) cat > "${PSQL_STDIN:-/dev/null}"; [ "${PSQL_FAIL_LOAD:-0}" = "1" ] && exit 1; : ;;
esac
exit 0
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
    for name, body in (("pg_dump", STUB_PG_DUMP), ("sleep", STUB_SLEEP), ("psql", STUB_PSQL)):
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
        "CALL_LOG": str(tmp_path / "calls.log"),
        "PSQL_STDIN": str(tmp_path / "loaded.sql"),
    }
    for var in (
        "BACKUP_HOUR",
        "BACKUP_LOCAL_RETENTION_DAYS",
        "STUB_FAIL",
        "STUB_EMPTY",
        "PSQL_FAIL_DROP",
        "PSQL_FAIL_LOAD",
    ):
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


# ── восстановление ───────────────────────────────────────────────────────────
SQL = b"CREATE TABLE restored(id int);\nINSERT INTO restored VALUES (42);\n"


def _calls(environ) -> list[str]:
    log = Path(environ["CALL_LOG"])
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _dump_file(out: Path, name: str = "db-2026-10-20_03-00-00.sql.gz", payload: bytes = SQL) -> Path:
    f = out / name
    f.write_bytes(gzip.compress(payload))
    return f


@needs_sh
def test_restore_without_file_lists_available_dumps(env):
    environ, out, _ = env
    _dump_file(out, "db-2026-10-20_03-00-00.sql.gz")
    result = _run(environ, "restore")
    assert result.returncode == 2
    assert "db-2026-10-20_03-00-00.sql.gz" in result.stdout
    assert _calls(environ) == []


@needs_sh
def test_restore_requires_explicit_confirmation(env):
    environ, out, _ = env
    _dump_file(out)
    result = _run(environ, "restore", "db-2026-10-20_03-00-00.sql.gz")
    assert result.returncode == 3 and "--yes" in result.stdout
    assert _calls(environ) == [], "без --yes база не должна затрагиваться"


@needs_sh
@pytest.mark.parametrize("name", ["missing.sql.gz", "../../etc/passwd-not-there.gz"])
def test_restore_rejects_missing_file(env, name):
    environ, out, _ = env
    result = _run(environ, "restore", name, "--yes")
    assert result.returncode == 1 and "не найден" in result.stdout
    assert _calls(environ) == []


@needs_sh
def test_restore_rejects_corrupt_file_before_touching_the_database(env):
    environ, out, _ = env
    (out / "db-2026-10-20_03-00-00.sql.gz").write_bytes(b"this is not gzip")
    result = _run(environ, "restore", "db-2026-10-20_03-00-00.sql.gz", "--yes")
    assert result.returncode == 1 and "повреждён" in result.stdout
    assert _calls(environ) == []


@needs_sh
def test_restore_saves_current_db_then_recreates_and_loads_the_dump(env):
    environ, out, _ = env
    _dump_file(out)
    result = _run(environ, "restore", "db-2026-10-20_03-00-00.sql.gz", "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(environ)
    kinds = [
        "pg_dump" if c.startswith("pg_dump") else "drop" if "DROP" in c else "load"
        for c in calls
        if "to_regclass" not in c and "count(*)" not in c and "alembic" not in c
    ]
    assert kinds == ["pg_dump", "drop", "load"], kinds  # сначала страховка, потом замена
    assert any('DROP DATABASE IF EXISTS "testdb" WITH (FORCE)' in c and 'CREATE DATABASE "testdb"' in c for c in calls)
    assert Path(environ["PSQL_STDIN"]).read_bytes() == SQL, "в psql должен уйти ровно распакованный дамп"
    guards = list(out.glob("pre-restore-*.sql.gz"))
    assert len(guards) == 1 and "CREATE TABLE t" in gzip.decompress(guards[0].read_bytes()).decode()
    assert "users: 7" in result.stdout and "версия миграций: n9c0d1e2f3a4" in result.stdout


@needs_sh
def test_restore_safety_copy_is_not_pruned_as_a_regular_dump(env):
    environ, out, _ = env
    _dump_file(out)
    _run(environ, "restore", "db-2026-10-20_03-00-00.sql.gz", "--yes")
    guard = next(out.glob("pre-restore-*.sql.gz"))
    stamp = time.time() - 400 * 86400
    os.utime(guard, (stamp, stamp))
    _run(environ, "once", BACKUP_LOCAL_RETENTION_DAYS="1")
    assert guard.exists(), "страховочная копия перед восстановлением не должна удаляться ротацией"


@needs_sh
def test_restore_no_safety_skips_the_copy(env):
    environ, out, _ = env
    _dump_file(out)
    result = _run(environ, "restore", "db-2026-10-20_03-00-00.sql.gz", "--yes", "--no-safety")
    assert result.returncode == 0
    assert not list(out.glob("pre-restore-*")) and not any(c.startswith("pg_dump") for c in _calls(environ))


@needs_sh
def test_restore_aborts_if_the_safety_copy_cannot_be_made(env):
    environ, out, _ = env
    _dump_file(out)
    result = _run(environ, "restore", "db-2026-10-20_03-00-00.sql.gz", "--yes", STUB_FAIL="1")
    assert result.returncode == 1 and "Восстановление отменено" in result.stdout
    assert not any("DROP" in c for c in _calls(environ)), "базу нельзя трогать, если не удалось её сохранить"
    assert not list(out.glob("pre-restore-*")) and not list(out.glob(".*"))


@needs_sh
def test_restore_reports_failure_when_dump_does_not_load(env):
    environ, out, _ = env
    _dump_file(out)
    result = _run(environ, "restore", "db-2026-10-20_03-00-00.sql.gz", "--yes", PSQL_FAIL_LOAD="1")
    assert result.returncode == 1 and "не залился" in result.stdout and "pre-restore" in result.stdout


@needs_sh
def test_restore_stops_if_database_cannot_be_recreated(env):
    environ, out, _ = env
    _dump_file(out)
    result = _run(environ, "restore", "db-2026-10-20_03-00-00.sql.gz", "--yes", PSQL_FAIL_DROP="1")
    assert result.returncode == 1 and "пересоздать" in result.stdout
    assert Path(environ["PSQL_STDIN"]).exists() is False


@needs_sh
def test_restore_rejects_unknown_option(env):
    environ, out, _ = env
    _dump_file(out)
    assert _run(environ, "restore", "db-2026-10-20_03-00-00.sql.gz", "--force").returncode == 2


@needs_sh
def test_restore_reads_the_newest_dump_made_by_the_service_itself(env):
    """Круг целиком: снятый сервисом дамп восстанавливается тем же сервисом."""
    environ, out, _ = env
    assert _run(environ, "once").returncode == 0
    (dump,) = _dumps(out)
    result = _run(environ, "restore", dump.name, "--yes", "--no-safety")
    assert result.returncode == 0, result.stdout
    assert b"CREATE TABLE t(id int);" in Path(environ["PSQL_STDIN"]).read_bytes()


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
