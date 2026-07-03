# src/services/storage_service.py
"""
Сервис для загрузки файлов вложений в Cloudflare R2.

R2 полностью совместим с S3 API, поэтому используем aioboto3
с кастомным endpoint_url вместо AWS.

Использование:
    storage = R2StorageService()
    url = await storage.upload(
        key="attachments/42/photo.jpg",
        data=file_bytes,
        content_type="image/jpeg",
    )
    # url -> публичная ссылка для фронта
"""

from __future__ import annotations

import uuid

import aioboto3
import structlog
from botocore.config import Config as BotoConfig

from src.core.config import (
    R2_ACCESS_KEY_ID,
    R2_ACCOUNT_ID,
    R2_BUCKET_NAME,
    R2_PUBLIC_BASE_URL,
    R2_SECRET_ACCESS_KEY,
)

logger = structlog.get_logger()


class R2NotConfiguredError(RuntimeError):
    """R2 переменные окружения не заданы."""


class R2StorageService:
    """
    Тонкая обёртка над aioboto3 для загрузки/удаления файлов в R2.

    R2 endpoint формата: https://<account_id>.r2.cloudflarestorage.com
    """

    def __init__(self) -> None:
        self.bucket = R2_BUCKET_NAME
        self.endpoint_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else ""
        self.public_base_url = R2_PUBLIC_BASE_URL

        self._session = aioboto3.Session()
        # auto_paging/retries — R2 иногда отдаёт 5xx при холодном старте бакета
        self._boto_config = BotoConfig(
            region_name="auto",  # R2 не использует регионы, но boto3 требует значение
            retries={"max_attempts": 3, "mode": "standard"},
            signature_version="s3v4",
        )

    @property
    def is_configured(self) -> bool:
        return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY)

    def _client(self):
        if not self.is_configured:
            raise R2NotConfiguredError(
                "R2 не настроен: задайте R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY в переменных окружения."
            )
        return self._session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=self._boto_config,
        )

    @staticmethod
    def build_key(task_id: int, filename: str) -> str:
        """
        Формирует уникальный путь в бакете.
        Пример: attachments/42/a1b2c3d4-photo.jpg
        """
        safe_name = filename.replace("/", "_").replace("\\", "_").strip() or "file"
        unique_prefix = uuid.uuid4().hex[:8]
        return f"attachments/{task_id}/{unique_prefix}-{safe_name}"

    async def upload(
        self,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        """
        Загружает файл в R2 и возвращает публичный URL.

        Raises:
            R2NotConfiguredError: если переменные окружения не заданы.
        """
        async with self._client() as s3:  # type: ignore[attr-defined]
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type

            await s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                **extra_args,
            )

        url = self.get_public_url(key)
        await logger.ainfo("r2_upload_success", key=key, size=len(data), url=url)
        return url

    def get_public_url(self, key: str) -> str:
        """
        Строит публичную ссылку на объект.

        Требует, чтобы бакет был опубликован (R2.dev domain
        или кастомный домен через Cloudflare).
        """
        if not self.public_base_url:
            # Без публичного домена ссылку строить нельзя —
            # тогда нужен presigned URL (см. get_presigned_url).
            return ""
        return f"{self.public_base_url}/{key}"

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Альтернатива публичному домену — временная подписанная ссылка.
        Полезно, если бакет приватный (нет R2_PUBLIC_BASE_URL).
        """
        async with self._client() as s3:  # type: ignore[attr-defined]
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        return url

    async def delete(self, key: str) -> None:
        async with self._client() as s3:  # type: ignore[attr-defined]
            await s3.delete_object(Bucket=self.bucket, Key=key)
        await logger.ainfo("r2_delete_success", key=key)


# Синглтон для использования в хендлерах/роутерах
storage_service = R2StorageService()
