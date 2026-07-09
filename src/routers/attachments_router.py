# src/routers/attachments_router.py
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from src.core.config import ATTACHMENTS_STORAGE_PATH
from src.core.dependencies import get_current_user
from src.core.exceptions import not_found
from src.db import SessionDep
from src.models.attachment_model import AttachmentModel
from src.models.user import UserModel
from src.repositories.attachment_repository import AttachmentRepository
from src.repositories.groups_repository import GroupRepository
from src.repositories.task_repository import TaskRepository
from src.schemas.attachment_schemas import AttachmentListResponse, AttachmentResponse
from src.services.active_storage import storage
from src.services.attachment_service import AttachmentService

# Базовая папка локального стораджа — для стриминга файлов через авторизованный эндпоинт
_LOCAL_STORAGE_BASE = Path(ATTACHMENTS_STORAGE_PATH).resolve()

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 МБ — лимит Telegram Bot API
ALLOWED_MIME_PREFIXES = ("image/", "video/", "audio/", "application/", "text/")


router = APIRouter(prefix="/attachments", tags=["Attachments"])


def _build_service(session: SessionDep) -> AttachmentService:
    return AttachmentService(
        task_repo=TaskRepository(session),
        attachment_repo=AttachmentRepository(session),
        session=session,
        group_repo=GroupRepository(session),
    )


def _to_response(attachment, download_url: str) -> AttachmentResponse:
    return AttachmentResponse(
        id=attachment.id,
        task_id=attachment.task_id,
        filename=attachment.filename,
        mime_type=attachment.mime_type,
        file_size=attachment.file_size,
        download_url=download_url,
        uploader=attachment.uploader,
        created_at=attachment.created_at,
    )


@router.post(
    "/tasks/{task_id}",
    response_model=AttachmentResponse,
    status_code=201,
    summary="Загрузить вложение к задаче",
    description="""
Принимает multipart/form-data с файлом, сохраняет в хранилище и привязывает к задаче.

Доступ — те же правила что у задачи (автор / исполнитель / группа / admin+manager).
Максимальный размер: 20 МБ.
""",
    responses={
        403: {"description": "Нет доступа к задаче"},
        404: {"description": "Задача не найдена"},
        413: {"description": "Файл превышает 20 МБ"},
    },
)
async def upload_attachment(
    task_id: int,
    session: SessionDep,
    file: UploadFile = File(...),
    current_user: UserModel = Depends(get_current_user),
):
    from fastapi import HTTPException

    service = _build_service(session)

    # Проверка доступа к задаче (бросает 403/404 через exceptions)
    await service._check_access(task_id, current_user)

    # Читаем файл целиком — нужен размер ДО сохранения на диск
    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой: {len(data) // (1024 * 1024)} МБ. Максимум 20 МБ.",
        )

    filename = file.filename or "file"
    mime_type = file.content_type

    # Сохраняем в storage (local или R2 в зависимости от active_storage.py)
    key = storage.build_key(task_id, filename)
    url = await storage.upload(key=key, data=data, content_type=mime_type)

    # Создаём запись в БД
    # telegram_file_id для веб-загрузки не заполняем (web upload, не бот)
    attachment = AttachmentModel(
        task_id=task_id,
        uploaded_by=current_user.id,
        filename=filename,
        mime_type=mime_type,
        file_size=len(data),
        telegram_file_id=None,  # web upload, не через бота
        storage_key=key,
        storage_url=url or None,
    )
    await service.attachment_repo.create(attachment)
    await session.commit()

    # Для local storage upload() вернул "", поэтому в download_url
    # отдаём авторизованный эндпоинт, а не пустую строку.
    download_url = url if url else f"/api/attachments/{attachment.id}/download"
    return _to_response(attachment, download_url)


@router.get(
    "/tasks/{task_id}",
    response_model=AttachmentListResponse,
    summary="Список вложений задачи",
    description="""
Возвращает все вложения задачи с готовыми ссылками для скачивания.

Доступ разрешён автору, исполнителю, членам группы задачи и admin/manager
— те же правила, что и для редактирования задачи.
""",
    responses={
        403: {"description": "Нет доступа к задаче"},
        404: {"description": "Задача не найдена"},
    },
)
async def list_task_attachments(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    service = _build_service(session)
    attachments = await service.list_for_task(task_id, current_user)

    items = []
    for att in attachments:
        # Всегда отдаём авторизованный эндпоинт — он проверяет JWT и права,
        # а затем либо стримит файл (local storage), либо делает presigned-редирект (R2).
        # НЕ передаём storage_url напрямую: локальные файлы больше не висят на публичном пути.
        download_url = f"/api/attachments/{att.id}/download"
        items.append(_to_response(att, download_url))

    return AttachmentListResponse(items=items, total=len(items))


@router.get(
    "/{attachment_id}/download",
    summary="Скачать вложение",
    description="""
Отдаёт файл вложения. Требует валидный JWT в заголовке Authorization.

Поведение зависит от активного backend хранилища:
- **Local storage** (текущий режим): файл стримится напрямую через FileResponse.
  Файл **никогда не доступен без авторизации** — StaticFiles mount отключён.
- **R2** (когда будет подключён): редирект на временную presigned-ссылку (1 час).
- **404**: файл не найден на диске или не синхронизирован с R2.
""",
    responses={
        200: {"description": "Файл (local storage)"},
        302: {"description": "Редирект на presigned URL (R2)"},
        403: {"description": "Нет доступа к вложению"},
        404: {"description": "Вложение не найдено"},
    },
)
async def download_attachment(
    attachment_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    from fastapi import HTTPException

    attachment_repo = AttachmentRepository(session)
    attachment = await attachment_repo.get_by_id(attachment_id)
    if not attachment:
        not_found("Вложение не найдено")

    # Проверяем доступ к родительской задаче
    service = _build_service(session)
    await service._check_access(attachment.task_id, current_user)

    # ── Local storage: стримим файл напрямую, без редиректа на публичный URL ──
    # Признак local storage — storage_key есть, storage_url пустой
    # (R2StorageService при upload пишет storage_url с https://...).
    if attachment.storage_key and not attachment.storage_url:
        file_path = _LOCAL_STORAGE_BASE / attachment.storage_key
        if not file_path.exists():
            not_found(
                "Файл не найден на диске. "
                "На Render free tier диск эфемерный — файлы пропадают при рестарте. "
                "Если файл был загружен давно, загрузите его повторно."
            )
        return FileResponse(
            path=str(file_path),
            filename=attachment.filename,
            media_type=attachment.mime_type or "application/octet-stream",
        )

    # ── R2 / внешнее хранилище: presigned-редирект ───────────────────────────
    if attachment.storage_key and storage.is_configured:
        presigned_url = await storage.get_presigned_url(attachment.storage_key)
        if presigned_url:
            return RedirectResponse(presigned_url, status_code=302)

    # ── Файл загружен только через бота (только telegram_file_id, нет storage_key) ──
    if attachment.telegram_file_id:
        raise HTTPException(
            status_code=404,
            detail="Этот файл доступен только в Telegram-боте. Запросите его командой /getfile.",
        )

    not_found("Файл недоступен через веб-интерфейс.")


@router.delete(
    "/{attachment_id}",
    status_code=204,
    summary="Удалить вложение",
    description="""
Удаляет вложение из БД и из R2 (если файл там есть).
Запись в Telegram (telegram_file_id) физически не удаляется — это файл в чате бота.
""",
    responses={
        403: {"description": "Нет доступа к вложению"},
        404: {"description": "Вложение не найдено"},
    },
)
async def delete_attachment(
    attachment_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    service = _build_service(session)
    await service.delete(attachment_id, current_user)
