#!/usr/bin/env bash
# scripts/backup.sh
#
# Бэкап Postgres для self-hosted-инстанса: pg_dump из контейнера postgres,
# локальная ротация + загрузка в тот же R2-бакет, что и вложения (см.
# scripts/upload_backup_to_r2.py), с прунингом старых бэкапов в бакете.
#
# Запускать с хоста, из корня проекта (там же, где docker-compose.yml и
# .env.prod), например по cron:
#   0 3 * * * cd /opt/spisok-del && ./scripts/backup.sh >> /var/log/spisok-backup.log 2>&1
#
# Требования: docker compose уже поднят (postgres и app должны быть живы;
# app — просто чтобы переиспользовать его образ с уже установленными
# зависимостями для шага загрузки в R2, сам он не обязан отвечать на запросы).

set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml"

mkdir -p backups

# Достаём переменные из .env.prod (POSTGRES_* для pg_dump, а также опциональные
# BACKUP_LOCAL_RETENTION_DAYS/BACKUP_REMOTE_RETENTION_DAYS) — ДО того, как
# резолвим ретеншен ниже, иначе значения из .env.prod будут молча
# проигнорированы и всегда возьмутся дефолты.
# shellcheck disable=SC1091
set -a
source .env.prod
set +a

# Локальная ротация — сколько последних дампов держим на диске сервера,
# НЕЗАВИСИМО от прунинга в R2 (тот настраивается отдельно, аргументом
# upload_backup_to_r2.py). Разные ретеншены осознанно: диск сервера дороже
# и меньше, чем R2, так что локально держим немного (быстрый rollback),
# а в R2 — дольше (настоящая история на случай катастрофы).
LOCAL_RETENTION_DAYS="${BACKUP_LOCAL_RETENTION_DAYS:-3}"
REMOTE_RETENTION_DAYS="${BACKUP_REMOTE_RETENTION_DAYS:-30}"

TIMESTAMP="$(date +%F_%H-%M-%S)"
DUMP_FILE="backups/db-${TIMESTAMP}.sql.gz"

echo "[backup] $(date -Iseconds) — снимаю дамп БД ${POSTGRES_DB}..."
$COMPOSE exec -T postgres pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}" | gzip > "${DUMP_FILE}"

SIZE=$(du -h "${DUMP_FILE}" | cut -f1)
echo "[backup] Дамп готов: ${DUMP_FILE} (${SIZE})"

echo "[backup] Чищу локальные дампы старше ${LOCAL_RETENTION_DAYS} дн..."
find backups -name "db-*.sql.gz" -mtime "+${LOCAL_RETENTION_DAYS}" -print -delete

echo "[backup] Загружаю в R2 (и чищу там бэкапы старше ${REMOTE_RETENTION_DAYS} дн)..."
$COMPOSE run --rm app python scripts/upload_backup_to_r2.py "/app/${DUMP_FILE}" "${REMOTE_RETENTION_DAYS}"

echo "[backup] $(date -Iseconds) — готово."
