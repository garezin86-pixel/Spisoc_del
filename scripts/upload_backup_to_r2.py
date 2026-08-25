# scripts/upload_backup_to_r2.py
"""
Загружает файл бэкапа БД в тот же R2-бакет, что и вложения (src/services/
storage_service.py), под префиксом backups/ — не заводим отдельный сервис
ради этого, R2-креды уже есть в .env.prod.

Синхронный boto3 (не aioboto3, как в остальном приложении) — это
одноразовый CLI-запуск из cron/backup.sh, а не часть FastAPI-приложения,
async тут не даёт никакой выгоды и только усложняет скрипт.

Использование:
    python scripts/upload_backup_to_r2.py /app/backups/db-2026-08-24.sql.gz

Дополнительно чистит в бакете бэкапы старше BACKUP_RETENTION_DAYS дней
(по умолчанию 30) — без этого R2-бакет будет расти бесконечно.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import (  # noqa: E402
    R2_ACCESS_KEY_ID,
    R2_ACCOUNT_ID,
    R2_BUCKET_NAME,
    R2_SECRET_ACCESS_KEY,
)

BACKUP_PREFIX = "backups/"
DEFAULT_RETENTION_DAYS = 30


def _client():
    if not (R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY):
        print(
            "R2 не настроен: задайте R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY в .env.prod — бэкап останется только локально.",
            file=sys.stderr,
        )
        sys.exit(1)
    session = boto3.Session()
    return session.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=BotoConfig(
            region_name="auto", retries={"max_attempts": 3, "mode": "standard"}, signature_version="s3v4"
        ),
    )


def upload(client, local_path: Path) -> None:
    key = f"{BACKUP_PREFIX}{local_path.name}"
    print(f"Загружаю {local_path} -> r2://{R2_BUCKET_NAME}/{key}")
    client.upload_file(str(local_path), R2_BUCKET_NAME, key)
    print("Загружено.")


def prune_old_backups(client, retention_days: int) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    paginator = client.get_paginator("list_objects_v2")
    deleted = 0
    for page in paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix=BACKUP_PREFIX):
        for obj in page.get("Contents", []):
            if obj["LastModified"] < cutoff:
                client.delete_object(Bucket=R2_BUCKET_NAME, Key=obj["Key"])
                deleted += 1
                print(f"Удалён старый бэкап: {obj['Key']} ({obj['LastModified'].date()})")
    print(f"Прунинг завершён: удалено {deleted} файлов старше {retention_days} дней.")


def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python scripts/upload_backup_to_r2.py <путь_к_файлу> [retention_days]", file=sys.stderr)
        sys.exit(1)

    local_path = Path(sys.argv[1])
    if not local_path.is_file():
        print(f"Файл не найден: {local_path}", file=sys.stderr)
        sys.exit(1)

    retention_days = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_RETENTION_DAYS

    client = _client()
    upload(client, local_path)
    prune_old_backups(client, retention_days)


if __name__ == "__main__":
    main()
