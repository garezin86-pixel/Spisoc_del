# src/services/local_storage_service.py
"""
Локальное файловое хранилище для вложений — временная замена R2.

Используется, пока не подключён Cloudflare R2. Имеет тот же публичный
интерфейс, что и R2StorageService (upload/get_public_url/delete), поэтому
переключение между ними — это просто замена импорта в одном месте
(src/bot/handlers/attachments.py и src/services/attachment_service.py).

ВНИМАНИЕ:
  На Render free tier файловая система ephemeral — все файлы пропадают
  при каждом рестарте/редеплое сервиса. Для прод-использования сначала
  переключайся на R2 (см. storage_service.py) или подключай Render
  persistent disk (платный план).

Файлы раздаются через FastAPI StaticFiles, примонтированный в src/main.py
на путь /attachments-storage.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles
import aiofiles.os
import structlog

from src.core.config import ATTACHMENTS_STORAGE_PATH

logger = structlog.get_logger()

# PUBLIC_URL_PREFIX убран — StaticFiles mount для вложений отключён.
# Файлы доступны только через авторизованный эндпоинт /api/attachments/{id}/download.


class LocalStorageService:
    """
    Хранит файлы на диске в ATTACHMENTS_STORAGE_PATH.

    Структура: storage/attachments/<task_id>/<uuid-prefix>-<filename>
    """

    def __init__(self) -> None:
        self.base_path = Path(ATTACHMENTS_STORAGE_PATH).resolve()

    @property
    def is_configured(self) -> bool:
        # Локальное хранилище всегда "настроено" — папка создаётся лениво
        return True

    def _ensure_base_dir(self) -> None:
        self.base_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def build_key(task_id: int | str, filename: str) -> str:
        """
        Формирует относительный путь файла.
        Пример: 42/a1b2c3d4-photo.jpg
        task_id может быть строкой (например "avatars/7" для аватаров
        пользователей, см. users_router.upload_my_avatar) — это просто
        префикс пути, а не число для арифметики.
        """
        safe_name = filename.replace("/", "_").replace("\\", "_").strip() or "file"
        unique_prefix = uuid.uuid4().hex[:8]
        return f"{task_id}/{unique_prefix}-{safe_name}"

    async def upload(
        self,
        key: str,
        data: bytes,
        content_type: str | None = None,  # noqa: ARG002 — не нужен для локального FS, оставлен для совместимости интерфейса
    ) -> str:
        """
        Сохраняет файл на диск.

        Возвращает пустую строку — намеренно, чтобы AttachmentModel.storage_url
        оставался None/пустым. Это является признаком «local storage» в роутере:
        эндпоинт /api/attachments/{id}/download увидит storage_url=None и
        стримит файл напрямую через FileResponse, без публичного URL.

        Ранее возвращался /attachments-storage/... — публичный путь StaticFiles.
        StaticFiles mount убран (файлы не должны быть доступны без авторизации).
        """
        self._ensure_base_dir()

        target_path = self.base_path / key
        await aiofiles.os.makedirs(target_path.parent, exist_ok=True)

        async with aiofiles.open(target_path, "wb") as f:
            await f.write(data)

        await logger.ainfo("local_storage_upload_success", key=key, size=len(data), path=str(target_path))
        # Возвращаем "" — storage_url в БД будет NULL.
        # Скачивание идёт через авторизованный эндпоинт, а не по прямой ссылке.
        return ""

    def get_public_url(self, key: str) -> str:
        """
        Оставлен для совместимости интерфейса с R2StorageService.
        Для локального стораджа публичных URL больше нет — используйте
        эндпоинт /api/attachments/{id}/download.
        """
        # Возвращаем пустую строку, а не /attachments-storage/... —
        # StaticFiles mount отключён, прямой путь никуда не ведёт.
        return ""

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:  # noqa: ARG002
        """
        У локального хранилища нет presigned ссылок.
        Возвращаем "" — вызывающий код должен стримить файл через FileResponse.
        """
        return ""

    async def delete(self, key: str) -> None:
        target_path = self.base_path / key
        try:
            await aiofiles.os.remove(target_path)
            await logger.ainfo("local_storage_delete_success", key=key)
        except FileNotFoundError:
            await logger.awarning("local_storage_delete_not_found", key=key)


# Синглтон — используется вместо storage_service из storage_service.py,
# пока R2 не подключён.
local_storage_service = LocalStorageService()
