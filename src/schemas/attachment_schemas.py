# src/schemas/attachment.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AttachmentUploaderSchema(BaseModel):
    id: int
    username: str

    model_config = ConfigDict(from_attributes=True)


class AttachmentResponse(BaseModel):
    id: int
    task_id: int
    filename: str
    mime_type: str | None
    file_size: int | None

    # URL для скачивания/превью с веба. Бэкенд сам решает, какой URL отдать:
    # - storage_url, если R2 настроен и файл уже синхронизирован
    # - иначе ссылка на наш собственный редирект-эндпоинт (который сходит
    #   за presigned URL или fallback на Telegram)
    download_url: str

    uploader: AttachmentUploaderSchema
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AttachmentListResponse(BaseModel):
    items: list[AttachmentResponse]
    total: int
