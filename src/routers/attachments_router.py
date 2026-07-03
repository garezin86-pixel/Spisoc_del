# src/routers/attachments_router.py
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import RedirectResponse

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

    return _to_response(attachment, url)


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
        # storage_url уже посчитан и закэширован в БД — без лишних запросов к R2
        url = att.storage_url or ""
        items.append(_to_response(att, url))

    return AttachmentListResponse(items=items, total=len(items))


@router.get(
    "/{attachment_id}/download",
    summary="Скачать вложение",
    description="""
Редиректит на рабочую ссылку файла:
- публичный URL в R2, если файл синхронизирован и бакет публичный;
- временная подписанная ссылка (1 час), если бакет приватный;
- 404, если файл ещё не успел синхронизироваться с R2 (доступен только в боте через /getfile).
""",
    responses={
        302: {"description": "Редирект на файл"},
        403: {"description": "Нет доступа к вложению"},
        404: {"description": "Вложение не найдено или ещё не синхронизировано с R2"},
    },
)
async def download_attachment(
    attachment_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    service = _build_service(session)
    url = await service.get_download_url(attachment_id, current_user)

    if not url:
        not_found("Файл ещё не синхронизирован с веб-хранилищем. Получите его в Telegram-боте командой /getfile.")

    return RedirectResponse(url, status_code=302)


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
