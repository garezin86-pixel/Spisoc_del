#!/bin/sh
# scripts/backup_loop.sh
#
# Сервис `backup` из docker-compose.yml: раз в сутки снимает дамп Postgres в /backups
# (на хосте это ./backups) и удаляет старые. Включён по умолчанию — отдельного cron не нужно.
#
# Файлы называются db-ГГГГ-ММ-ДД_ЧЧ-ММ-СС.sql.gz — так же, как у scripts/backup.sh, поэтому выгрузка в R2
# (scripts/upload_backup_to_r2.py) и восстановление работают с ними одинаково.
#
# Запуск:
#   backup_loop.sh        — цикл: дамп при старте (если за сутки его ещё не было), затем каждый день в BACKUP_HOUR
#   backup_loop.sh once   — один дамп и выход (ручной бэкап: `docker compose run --rm backup once`)
#   backup_loop.sh restore [ФАЙЛ] [--yes] [--no-safety]
#                         — восстановить БД из дампа (`docker compose run --rm backup restore db-….sql.gz --yes`).
#                           Без ФАЙЛа показывает доступные дампы. Без --yes ничего не делает. ЗАМЕНЯЕТ текущую БД
#                           целиком; перед этим сохраняет её в pre-restore-….sql.gz (отключается --no-safety).
#                           Приложение перед восстановлением остановите: `docker compose stop app bot`.
#
# Настройки (переменные окружения):
#   PGHOST/PGUSER/PGPASSWORD/PGDATABASE      — подключение к БД (задаёт docker-compose.yml)
#   BACKUP_HOUR                  — час запуска, 0-23, по UTC (по умолчанию 3)
#   BACKUP_LOCAL_RETENTION_DAYS  — сколько дней хранить дампы (по умолчанию 7)
#   BACKUP_DIR                   — куда писать (по умолчанию /backups)
#
# POSIX sh (busybox в postgres:*-alpine): без bash-специфики и без pipefail.

set -eu
umask 077  # в дампе вся база: читать его может только владелец

DIR="${BACKUP_DIR:-/backups}"
HOUR="${BACKUP_HOUR:-3}"
KEEP_DAYS="${BACKUP_LOCAL_RETENTION_DAYS:-7}"
MIN_KEEP=3  # столько последних дампов не удаляем никогда, даже если все они «старые» (сбой часов, долгий простой)

log() { echo "[backup] $(date '+%F %T') UTC — $*"; }

case "$HOUR" in
  ''|*[!0-9]*) log "BACKUP_HOUR должен быть числом 0-23, а не '$HOUR'"; exit 2 ;;
esac
if [ "$HOUR" -gt 23 ]; then log "BACKUP_HOUR должен быть 0-23, а не '$HOUR'"; exit 2; fi
case "$KEEP_DAYS" in
  ''|*[!0-9]*) log "BACKUP_LOCAL_RETENTION_DAYS должен быть числом, а не '$KEEP_DAYS'"; exit 2 ;;
esac

mkdir -p "$DIR"

# Один дамп: пишем во временный файл и переименовываем в db-*.sql.gz только целиком готовый и непустой,
# чтобы оборванный дамп (нет места, сеть, перезапуск) не выглядел как хороший бэкап.
dump_once() {
  stamp="$(date '+%F_%H-%M-%S')"
  sql="$DIR/.db-$stamp.sql"
  final="$DIR/db-$stamp.sql.gz"
  log "снимаю дамп ${PGDATABASE:-БД}..."
  if pg_dump --no-owner --no-privileges -f "$sql" && [ -s "$sql" ] && gzip -9 -f "$sql" && [ -s "$sql.gz" ]; then
    mv "$sql.gz" "$final"
    log "готово: $final ($(du -h "$final" | cut -f1))"
    return 0
  fi
  rm -f "$sql" "$sql.gz"
  log "ОШИБКА: дамп не получился, файл не сохранён"
  return 1
}

# Удаляем дампы старше KEEP_DAYS, но MIN_KEEP самых свежих оставляем всегда.
prune() {
  # shellcheck disable=SC2012  # имена файлов наши (без пробелов), ls -t нужен ради сортировки по времени
  ls -1t "$DIR"/db-*.sql.gz 2>/dev/null | tail -n +$((MIN_KEEP + 1)) | while read -r file; do
    if [ -n "$(find "$file" -mtime "+$KEEP_DAYS" 2>/dev/null)" ]; then
      rm -f "$file" && log "удалён старый дамп: $file"
    fi
  done
  return 0
}

has_recent_dump() {
  [ -n "$(find "$DIR" -maxdepth 1 -name 'db-*.sql.gz' -mmin -1440 2>/dev/null | head -n 1)" ]
}

# Секунд до ближайшего HOUR:00 по UTC (сегодня, если час ещё не наступил, иначе завтра).
seconds_until_next_run() {
  h="$(date +%H)"; m="$(date +%M)"; s="$(date +%S)"
  h="${h#0}"; m="${m#0}"; s="${s#0}"   # «08» в арифметике sh — не число
  now=$(( ${h:-0} * 3600 + ${m:-0} * 60 + ${s:-0} ))
  wait=$(( HOUR * 3600 - now ))
  [ "$wait" -le 0 ] && wait=$(( wait + 86400 ))
  echo "$wait"
}

# Восстановление из дампа: проверяет файл, сохраняет текущую БД «на случай», пересоздаёт БД и заливает дамп.
restore_db() {
  file=""; confirmed=0; safety=1
  for arg in "$@"; do
    case "$arg" in
      --yes) confirmed=1 ;;
      --no-safety) safety=0 ;;
      -*) log "неизвестный параметр: $arg"; return 2 ;;
      *) file="$arg" ;;
    esac
  done
  if [ -z "$file" ]; then
    log "укажите файл дампа. Доступные:"
    # shellcheck disable=SC2012
    ls -1t "$DIR"/db-*.sql.gz 2>/dev/null | while read -r f; do echo "  $(basename "$f")  ($(du -h "$f" | cut -f1))"; done
    return 2
  fi
  case "$file" in /*) path="$file" ;; *) path="$DIR/$file" ;; esac
  if [ ! -s "$path" ]; then log "ОШИБКА: файл не найден или пуст: $path"; return 1; fi
  if ! gzip -t "$path" 2>/dev/null; then log "ОШИБКА: файл повреждён (не проходит проверку gzip): $path"; return 1; fi
  if [ "$confirmed" -ne 1 ]; then
    log "будет ПОЛНОСТЬЮ заменена база ${PGDATABASE:-?} данными из $path"
    log "остановите приложение (docker compose stop app bot) и повторите команду с --yes"
    return 3
  fi

  if [ "$safety" -eq 1 ]; then
    guard="$DIR/pre-restore-$(date '+%F_%H-%M-%S').sql.gz"
    log "сохраняю текущую БД перед заменой: $guard"
    if pg_dump --no-owner --no-privileges -f "$guard.sql" && gzip -9 -f "$guard.sql" && mv "$guard.sql.gz" "$guard"; then
      log "текущее состояние сохранено"
    else
      rm -f "$guard.sql" "$guard.sql.gz" "$guard"
      log "ОШИБКА: не удалось сохранить текущую БД. Восстановление отменено (повторите с --no-safety, если текущая БД не нужна)"
      return 1
    fi
  fi

  log "пересоздаю базу ${PGDATABASE}..."
  psql -d postgres -v ON_ERROR_STOP=1 -q \
    -c "DROP DATABASE IF EXISTS \"$PGDATABASE\" WITH (FORCE)" -c "CREATE DATABASE \"$PGDATABASE\"" || {
    log "ОШИБКА: не удалось пересоздать базу"; return 1; }
  log "заливаю дамп..."
  if ! gunzip -c "$path" | psql -v ON_ERROR_STOP=1 -q -o /dev/null; then
    log "ОШИБКА: дамп не залился полностью. База в неполном состоянии — восстановите из pre-restore-*.sql.gz или другого дампа"
    return 1
  fi
  log "готово. Что в базе сейчас:"
  for t in users workspaces clients deals spisok_del; do
    if [ "$(psql -At -c "SELECT to_regclass('public.$t') IS NOT NULL" 2>/dev/null)" = "t" ]; then
      log "  $t: $(psql -At -c "SELECT count(*) FROM public.$t")"
    fi
  done
  log "  версия миграций: $(psql -At -c 'SELECT version_num FROM alembic_version' 2>/dev/null)"
  log "теперь запустите приложение: docker compose up -d (недостающие миграции применятся при старте)"
  return 0
}

if [ "${1:-}" = "restore" ]; then
  shift
  restore_db "$@"
  exit $?
fi

if [ "${1:-}" = "once" ]; then
  dump_once && prune
  exit $?
fi

log "сервис запущен: дамп раз в сутки в ${HOUR}:00 UTC, храню ${KEEP_DAYS} дн. (минимум ${MIN_KEEP} последних)"

# Первый запуск или долгий простой: не ждём до ночи, снимаем дамп сразу — иначе первые сутки без бэкапа.
if ! has_recent_dump; then
  until dump_once; do
    log "повтор через 10 минут"
    sleep 600
  done
  prune
fi

while true; do
  wait="$(seconds_until_next_run)"
  log "следующий дамп через $((wait / 3600)) ч $((wait % 3600 / 60)) мин"
  sleep "$wait"
  until dump_once; do
    log "повтор через 10 минут"
    sleep 600
  done
  prune
done
