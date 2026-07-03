# src/bot/handlers/attachments.py
"""
Обработчик вложений к задачам.

Флоу:
  1. Пользователь отправляет файл боту (document / photo / video / audio / voice).
  2. Если task_id уже выбран (/attach 42 или FSM-состояние) — сразу сохраняем.
  3. Если нет — просим ввести ID задачи, сохраняем файл в FSM, потом создаём.

Команды:
  /attach <task_id>  — установить активную задачу и сразу ждать файл
  /attachments <task_id>  — показать список вложений задачи
"""

from __future__ import annotations

import asyncio

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.bot.keyboards.main import cancel_keyboard
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.attachment_model import AttachmentModel
from src.services.active_storage import storage

logger = structlog.get_logger()
router = Router()

# Максимальный размер файла для MVP (20 МБ — лимит Telegram Bot API)
MAX_FILE_SIZE = 20 * 1024 * 1024

# Типы файлов которые принимаем.
# F.voice исключён — голосовые перехватывает voice_router (AI-обработчик).
CONTENT_TYPES = F.document | F.photo | F.video | F.audio


# ─── FSM ─────────────────────────────────────────────────────────────────────


class AttachFile(StatesGroup):
    waiting_for_task_id = State()  # ждём ID задачи после получения файла
    waiting_for_file = State()  # ждём файл после /attach <id>


# ─── Вспомогательные функции ──────────────────────────────────────────────────


def _extract_file_info(
    message: Message,
) -> tuple[str, str, str | None, int | None] | None:
    """
    Извлекает (file_id, filename, mime_type, file_size) из сообщения.
    Возвращает None если тип не поддерживается.
    """
    if message.document:
        d = message.document
        return (
            d.file_id,
            d.file_name or "file",
            d.mime_type,
            d.file_size,
        )
    if message.photo:
        p = message.photo[-1]  # берём самое большое
        return (p.file_id, "photo.jpg", "image/jpeg", p.file_size)
    if message.video:
        v = message.video
        return (
            v.file_id,
            v.file_name or "video.mp4",
            v.mime_type,
            v.file_size,
        )
    if message.audio:
        a = message.audio
        return (
            a.file_id,
            a.file_name or "audio",
            a.mime_type,
            a.file_size,
        )
    return None


async def _upload_to_storage_background(
    attachment_id: int,
    file_id: str,
    task_id: int,
    filename: str,
    mime_type: str | None,
) -> None:
    """
    Фоновая задача: скачивает файл из Telegram через bot.download()
    и сохраняет его в активном storage backend (сейчас — локальный диск,
    позже — Cloudflare R2, см. src/services/active_storage.py).

    Запускается через asyncio.create_task — не блокирует ответ пользователю.
    Ошибки логируются, но не приводят к падению бота: telegram_file_id
    остаётся рабочим запасным вариантом, даже если storage недоступен.
    """
    if not storage.is_configured:
        await logger.awarning(
            "storage_upload_skipped",
            reason="not_configured",
            attachment_id=attachment_id,
        )
        return

    try:
        from src.bot.setup import get_bot

        bot = get_bot()

        # bot.download() возвращает BytesIO с содержимым файла
        file_buffer = await bot.download(file_id)
        if file_buffer is None:
            await logger.aerror(
                "storage_upload_failed",
                reason="empty_buffer",
                attachment_id=attachment_id,
            )
            return

        file_bytes = file_buffer.read()
        key = storage.build_key(task_id, filename)

        url = await storage.upload(key=key, data=file_bytes, content_type=mime_type)

        async with UnitOfWork(get_session_maker()) as uow:
            att = await uow.attachments.get_by_id(attachment_id)
            if att:
                att.storage_key = key
                att.storage_url = url or None
                await uow.commit()

        await logger.ainfo("storage_upload_complete", attachment_id=attachment_id, key=key)

    except Exception as e:  # noqa: BLE001 — фоновая задача не должна ронять бота
        await logger.aerror("storage_upload_failed", attachment_id=attachment_id, error=str(e))


async def _save_attachment(
    message: Message,
    task_id: int,
    file_id: str,
    filename: str,
    mime_type: str | None,
    file_size: int | None,
) -> bool:
    """
    Сохраняет вложение в БД. Возвращает True при успехе.
    Параллельно запускает фоновую заливку файла в R2 (не блокирует ответ).
    """
    async with UnitOfWork(get_session_maker()) as uow:
        # Проверяем что задача существует и не удалена
        task = await uow.tasks.get_by_id(task_id)
        if not task:
            await message.answer(f"❌ Задача #{task_id} не найдена.")
            return False

        # Проверяем что пользователь имеет доступ к задаче
        if message.from_user is None:
            return False

        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ Пользователь не найден.")
            return False

        is_author = task.author_id == user.id
        is_assignee = task.user_id == user.id
        is_admin = user.role in ("admin", "manager")

        if not (is_author or is_assignee or is_admin):
            await message.answer(
                f"⛔ У вас нет доступа к задаче #{task_id}.\nВложение можно добавить только к своей задаче."
            )
            return False

        attachment = AttachmentModel(
            task_id=task_id,
            uploaded_by=user.id,
            filename=filename,
            mime_type=mime_type,
            file_size=file_size,
            telegram_file_id=file_id,
        )
        await uow.attachments.create(attachment)
        await uow.commit()

        await logger.ainfo(
            "attachment_created",
            attachment_id=attachment.id,
            task_id=task_id,
            user_id=user.id,
            filename=filename,
        )

        attachment_id = attachment.id

    # Заливка в R2 — вне транзакции UoW, не блокирует ответ пользователю
    asyncio.create_task(_upload_to_storage_background(attachment_id, file_id, task_id, filename, mime_type))

    return True


def _fmt_size(size: int | None) -> str:
    if not size:
        return "?"
    if size < 1024:
        return f"{size} Б"
    if size < 1024**2:
        return f"{size // 1024} КБ"
    return f"{size // 1024**2} МБ"


# ─── Команда /attach <task_id> ───────────────────────────────────────────────


@router.message(Command("attach"))
async def cmd_attach(message: Message, command: CommandObject, state: FSMContext):
    """
    /attach 42 — установить активную задачу и ждать файл.
    """
    args = command.args
    if not args or not args.strip().isdigit():
        await message.answer(
            "📎 <b>Прикрепить файл к задаче</b>\n\n"
            "Использование: <code>/attach &lt;ID задачи&gt;</code>\n"
            "Например: <code>/attach 42</code>\n\n"
            "После команды просто отправьте файл.",
            parse_mode="HTML",
        )
        return

    task_id = int(args.strip())

    # Проверяем задачу заранее
    async with UnitOfWork(get_session_maker()) as uow:
        task = await uow.tasks.get_by_id(task_id)
        if not task:
            await message.answer(f"❌ Задача #{task_id} не найдена.")
            return

    await state.set_state(AttachFile.waiting_for_file)
    await state.update_data(target_task_id=task_id)

    await message.answer(
        f"📎 Готов принять файл для задачи <b>#{task_id}: {task.title}</b>\n\n"
        "Отправьте файл, фото, видео или голосовое сообщение.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


# ─── Получение файла в состоянии waiting_for_file ────────────────────────────


@router.message(AttachFile.waiting_for_file, CONTENT_TYPES)
async def receive_file_with_task(message: Message, state: FSMContext):
    """Файл пришёл после /attach <id> — task_id уже в state."""
    data = await state.get_data()
    task_id: int = data["target_task_id"]

    info = _extract_file_info(message)
    if not info:
        await message.answer("❌ Не удалось определить тип файла.")
        return

    file_id, filename, mime_type, file_size = info

    if file_size and file_size > MAX_FILE_SIZE:
        await message.answer(
            f"❌ Файл слишком большой ({_fmt_size(file_size)}).\nМаксимум: {_fmt_size(MAX_FILE_SIZE)}."
        )
        return

    success = await _save_attachment(message, task_id, file_id, filename, mime_type, file_size)

    if success:
        from src.bot.utils.user_utils import get_main_menu

        async with UnitOfWork(get_session_maker()) as uow:
            if message.from_user is None:
                return
            user = await uow.users.get_by_telegram_id(message.from_user.id)

        await state.clear()
        await message.answer(
            f"✅ <b>{filename}</b> прикреплён к задаче #{task_id}.",
            parse_mode="HTML",
            reply_markup=get_main_menu(user) if user else None,
        )
    else:
        await state.clear()


# ─── Отмена при ожидании файла ───────────────────────────────────────────────


@router.message(AttachFile.waiting_for_file, F.text == "❌ Отмена")
@router.message(AttachFile.waiting_for_task_id, F.text == "❌ Отмена")
async def cancel_attach(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Прикрепление файла отменено.")


# ─── Файл без контекста (не в FSM) ───────────────────────────────────────────


@router.message(CONTENT_TYPES)
async def receive_file_no_context(message: Message, state: FSMContext):
    """
    Пользователь кинул файл без предварительной команды.
    Сохраняем файл в FSM и просим ID задачи.
    """
    info = _extract_file_info(message)
    if not info:
        return  # не наш тип — пусть другие хендлеры обработают

    file_id, filename, mime_type, file_size = info

    if file_size and file_size > MAX_FILE_SIZE:
        await message.answer(
            f"❌ Файл слишком большой ({_fmt_size(file_size)}).\nМаксимум: {_fmt_size(MAX_FILE_SIZE)}."
        )
        return

    await state.set_state(AttachFile.waiting_for_task_id)
    await state.update_data(
        pending_file_id=file_id,
        pending_filename=filename,
        pending_mime_type=mime_type,
        pending_file_size=file_size,
    )

    await message.answer(
        f"📎 Получен файл <b>{filename}</b> ({_fmt_size(file_size)}).\n\nК какой задаче прикрепить? Введите ID задачи:",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


# ─── Получение ID задачи в состоянии waiting_for_task_id ─────────────────────


@router.message(AttachFile.waiting_for_task_id, F.text.regexp(r"^\d+$"))
async def receive_task_id_for_file(message: Message, state: FSMContext):
    """Пользователь ввёл ID задачи — сохраняем файл."""
    if message.text is None:
        return
    task_id = int(message.text.strip())
    data = await state.get_data()

    file_id: str = data["pending_file_id"]
    filename: str = data["pending_filename"]
    mime_type: str | None = data.get("pending_mime_type")
    file_size: int | None = data.get("pending_file_size")

    success = await _save_attachment(message, task_id, file_id, filename, mime_type, file_size)

    if success:
        from src.bot.utils.user_utils import get_main_menu

        async with UnitOfWork(get_session_maker()) as uow:
            if message.from_user is None:
                return
            user = await uow.users.get_by_telegram_id(message.from_user.id)

        await state.clear()
        await message.answer(
            f"✅ <b>{filename}</b> прикреплён к задаче #{task_id}.",
            parse_mode="HTML",
            reply_markup=get_main_menu(user) if user else None,
        )
    else:
        await state.clear()


@router.message(AttachFile.waiting_for_task_id)
async def receive_task_id_invalid(message: Message, state: FSMContext):
    """Некорректный ввод вместо ID."""
    await message.answer(
        "⚠️ Введите числовой ID задачи. Например: <code>42</code>",
        parse_mode="HTML",
    )


# ─── Команда /attachments <task_id> ─────────────────────────────────────────


@router.message(Command("attachments"))
async def cmd_list_attachments(message: Message, command: CommandObject):
    """
    /attachments 42 — показать все вложения задачи.
    """
    args = command.args
    if not args or not args.strip().isdigit():
        await message.answer(
            "📎 <b>Список вложений задачи</b>\n\n"
            "Использование: <code>/attachments &lt;ID задачи&gt;</code>\n"
            "Например: <code>/attachments 42</code>",
            parse_mode="HTML",
        )
        return

    task_id = int(args.strip())

    async with UnitOfWork(get_session_maker()) as uow:
        task = await uow.tasks.get_by_id(task_id)
        if not task:
            await message.answer(f"❌ Задача #{task_id} не найдена.")
            return

        attachments = await uow.attachments.get_by_task_id(task_id)

    if not attachments:
        await message.answer(
            f"📎 У задачи <b>#{task_id}: {task.title}</b> нет вложений.\n\nДобавить: <code>/attach {task_id}</code>",
            parse_mode="HTML",
        )
        return

    lines = [f"📎 <b>Вложения задачи #{task_id}: {task.title}</b>\n"]
    for i, att in enumerate(attachments, 1):
        size_str = _fmt_size(att.file_size)
        uploader = att.uploader.username if att.uploader else "?"
        lines.append(
            f"{i}. <b>{att.filename}</b> — {size_str}\n"
            f"   👤 {uploader} · 🗓 {att.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"   ID вложения: <code>{att.id}</code>"
        )

    lines.append("\n📤 Чтобы получить файл: /getfile &lt;ID вложения&gt;")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── Команда /getfile <attachment_id> — отправить файл ───────────────────────


@router.message(Command("getfile"))
async def cmd_get_file(message: Message, command: CommandObject):
    """
    /getfile 7 — переслать файл пользователю по ID вложения.
    """
    args = command.args
    if not args or not args.strip().isdigit():
        await message.answer(
            "📤 Использование: <code>/getfile &lt;ID вложения&gt;</code>",
            parse_mode="HTML",
        )
        return

    att_id = int(args.strip())

    async with UnitOfWork(get_session_maker()) as uow:
        att = await uow.attachments.get_by_id(att_id)
        if not att:
            await message.answer(f"❌ Вложение #{att_id} не найдено.")
            return

        # Проверяем доступ через задачу
        task = await uow.tasks.get_by_id(att.task_id)
        if message.from_user is None:
            return
        user = await uow.users.get_by_telegram_id(message.from_user.id)

        if not task or not user:
            await message.answer("❌ Нет доступа.")
            return

        is_author = task.author_id == user.id
        is_assignee = task.user_id == user.id
        is_admin = user.role in ("admin", "manager")

        if not (is_author or is_assignee or is_admin):
            await message.answer("⛔ У вас нет доступа к этому файлу.")
            return

        file_id = att.telegram_file_id
        caption = f"📎 <b>{att.filename}</b>\nЗадача #{att.task_id}"

    # Файл загружен через веб-интерфейс — у него нет telegram_file_id
    if not file_id:
        storage_url = att.storage_url or ""
        await message.answer(
            f"📎 <b>{att.filename}</b> загружен через веб-интерфейс.\n"
            f"Скачать можно по ссылке в приложении.\n\n" + (f"🔗 {storage_url}" if storage_url else ""),
            parse_mode="HTML",
        )
        return

    # Пересылаем файл по file_id — тип определяем по mime_type
    mime = att.mime_type or ""
    try:
        if mime.startswith("image/"):
            await message.answer_photo(file_id, caption=caption, parse_mode="HTML")
        elif mime.startswith("video/"):
            await message.answer_video(file_id, caption=caption, parse_mode="HTML")
        elif mime.startswith("audio/") and "ogg" in mime:
            await message.answer_voice(file_id, caption=caption, parse_mode="HTML")
        elif mime.startswith("audio/"):
            await message.answer_audio(file_id, caption=caption, parse_mode="HTML")
        else:
            await message.answer_document(file_id, caption=caption, parse_mode="HTML")
    except Exception as e:
        await logger.aerror("getfile_failed", attachment_id=att_id, error=str(e))
        await message.answer("❌ Не удалось отправить файл. Возможно, файл устарел в Telegram.")


# ─── Кнопка меню «📎 Вложения» ────────────────────────────────────────────────


@router.message(F.text == "📎 Вложения")
async def menu_attachments(message: Message):
    """
    Кнопка главного меню — показывает инструкцию по работе с вложениями.
    """
    await message.answer(
        "📎 <b>Вложения к задачам</b>\n\n"
        "<b>Прикрепить файл:</b>\n"
        "• <code>/attach 42</code> — выбрать задачу, затем отправить файл\n"
        "• Или просто киньте файл боту — он спросит ID задачи\n\n"
        "<b>Просмотреть вложения:</b>\n"
        "• <code>/attachments 42</code> — список файлов задачи\n\n"
        "<b>Получить файл:</b>\n"
        "• <code>/getfile 7</code> — скачать вложение по его ID\n\n"
        "<b>Поддерживаемые типы:</b>\n"
        "📄 Документы · 🖼 Фото · 🎬 Видео · 🎵 Аудио\n"
        "Максимальный размер: <b>20 МБ</b>",
        parse_mode="HTML",
    )


# ─── Кнопка меню «❓ Шпаргалка» ──────────────────────────────────────────────

CHEATSHEET_TEXT = """❓ <b>Шпаргалка по командам</b>

<b>📋 Задачи</b>
/my — мои задачи
/today — на сегодня
/overdue — просроченные
/stats — моя статистика
/find <i>текст</i> — поиск

<b>➕ Создание</b>
/new <i>Название</i>
/new <i>Название | 25.12.2025</i>
/new <i>Название | дата | @user</i>

<b>🔄 Действия</b>
/task 42 — просмотр задачи
/done 42 — выполнено
/undone 42 — снять отметку
/del 42 — в корзину

<b>👥 Группы</b>
/group 3 — задачи группы

<b>📎 Вложения</b>
/attach 42 — прикрепить файл
/attachments 42 — список файлов
/getfile 7 — получить файл

<b>🎤 Голосовые</b>
/voice — шпаргалка по голосу"""


@router.message(F.text == "❓ Шпаргалка")
async def menu_cheatsheet(message: Message):
    await message.answer(CHEATSHEET_TEXT, parse_mode="HTML")


@router.message(F.text.in_({"❓ Помощь", "/help"}))
async def cmd_help(message: Message):
    await message.answer(CHEATSHEET_TEXT, parse_mode="HTML")
