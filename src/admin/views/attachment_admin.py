import structlog
from sqladmin import ModelView

from src.models import AttachmentModel
from src.services.active_storage import storage
from src.utils.datetime_utils import to_local

logger = structlog.get_logger()


def format_size(size: int | None) -> str:
    if size is None:
        return "-"

    value = float(size)

    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{value:.1f} TB"


# ─────────────────────────────────────────────
# 👥 Вложения
# ─────────────────────────────────────────────
class AttachmentAdmin(ModelView, model=AttachmentModel):
    name = "Вложение"
    name_plural = "Вложения"
    icon = "fa-solid fa-paperclip"

    # ВАЖНО: создание отключено. Форма ниже не включает task_id/uploaded_by
    # (оба NOT NULL в модели) — попытка создать запись через админку упала бы
    # с IntegrityError. Но даже если бы поля были добавлены, запись без
    # реального файла за ней (storage_key/telegram_file_id) была бы мёртвой:
    # клик по "скачать" в приложении вернул бы 404. Вложения должны появляться
    # только через настоящую загрузку (бот или POST /api/attachments/tasks/{id}).
    can_create = False

    column_list = [
        AttachmentModel.id,
        AttachmentModel.filename,
        AttachmentModel.mime_type,
        AttachmentModel.task,
        AttachmentModel.file_size,
    ]
    column_searchable_list = [AttachmentModel.filename]
    column_sortable_list = [AttachmentModel.id, AttachmentModel.filename]
    column_default_sort = [(AttachmentModel.id, False)]

    column_details_list = [
        AttachmentModel.id,
        AttachmentModel.filename,
        AttachmentModel.mime_type,
        AttachmentModel.file_size,
        AttachmentModel.telegram_file_id,
        AttachmentModel.storage_key,
        AttachmentModel.storage_url,
        AttachmentModel.task,
        AttachmentModel.created_at,
        AttachmentModel.uploader,
    ]
    # Редактировать можно только метаданные — не storage_key/storage_url
    # (это внутренние поля синхронизации с R2/локальным хранилищем; ручное
    # изменение оторвало бы запись от реального файла на диске/в R2).
    form_columns = [AttachmentModel.filename, AttachmentModel.mime_type]

    column_labels = {
        "id": "ID",
        "filename": "Название",
        "mime_type": "Тип MIME",
        "file_size": "Размер файла",
        "telegram_file_id": "ID файла в Telegram",
        "storage_key": "Ключ хранилища",
        "storage_url": "URL хранилища",
        "task": "Задача",
        "uploader": "Кто загрузил",
        "created_at": "Дата загрузки",
    }

    column_formatters_detail = {
        AttachmentModel.created_at: lambda m, a: to_local(m.created_at),
        AttachmentModel.file_size: lambda m, a: format_size(m.file_size),
        AttachmentModel.storage_url: lambda m, a: m.storage_url or "Локальное хранение",
        AttachmentModel.storage_key: lambda m, a: m.storage_key or "—",
    }

    column_formatters = {
        AttachmentModel.file_size: lambda m, a: format_size(m.file_size),
    }

    async def on_model_delete(self, model, request) -> None:
        """
        Удаление через SQLAdmin по умолчанию — это просто `session.delete()`,
        без вызова AttachmentService.delete(). Из-за этого R2-файл оставался
        бы висеть вечно (orphan) при удалении записи через админку — сам
        API-эндпоинт удаления чистит R2, а админка в обход этого сервиса
        удаляла бы только строку в БД. Дублируем очистку здесь.

        Локальный сторадж НЕ чистим по той же причине, по которой это не
        делает и сам AttachmentService.delete() — см. соответствующий тикет/
        комментарий там же: сейчас это отдельный, более широкий пробел (файлы
        в локальном хранилище не удаляются вообще нигде), а не специфика
        админки — чинить стоит в одном месте (сервисе), не здесь.
        """
        if model.storage_key and storage.is_configured:
            try:
                await storage.delete(model.storage_key)
            except Exception as e:  # noqa: BLE001
                await logger.awarning(
                    "r2_delete_failed_on_admin_attachment_delete",
                    attachment_id=model.id,
                    error=str(e),
                )
