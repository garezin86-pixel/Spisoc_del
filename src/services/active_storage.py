# src/services/active_storage.py
"""
Единая точка выбора storage backend для вложений.

Сейчас активен LocalStorageService (локальный диск) — R2 ещё не подключён.

Когда будешь готов переключиться на Cloudflare R2:
  1. Заполни R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY в .env
  2. Поменяй ОДНУ строку ниже: storage = local_storage_service → storage = storage_service
  3. Опционально: мигрируй уже загруженные файлы из storage/attachments в R2 вручную

Всё остальное (bot handler, attachment_service, API роутер) обращается
только к этому модулю и ничего не знает про конкретный backend.
"""

from src.services.local_storage_service import local_storage_service

# ── Текущий активный backend ──────────────────────────────────────────────
storage = local_storage_service

# Когда подключишь R2, замени строку выше на:
# from src.services.storage_service import storage_service
# storage = storage_service


class StorageNotConfiguredError(RuntimeError):
    """Универсальная ошибка — backend не настроен (актуально для R2)."""
