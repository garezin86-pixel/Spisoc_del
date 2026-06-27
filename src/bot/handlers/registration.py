import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.core.config import SUPER_ADMIN_TG_ID
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.user import UserModel

router = Router()
logger = structlog.get_logger()


pending_registrations: dict[int, str] = {}  # tg_id: fio


class Registration(StatesGroup):
    waiting_for_fio = State()


@router.message(F.text == "📝 Подать заявку")
async def registration_start(message: Message, state: FSMContext):
    await state.set_state(Registration.waiting_for_fio)
    await message.answer("👤 Введите ваше ФИО (Фамилия Имя Отчество):\n\nНапример: Иванов Иван Иванович")


@router.message(Registration.waiting_for_fio)
async def registration_fio(message: Message, state: FSMContext):
    assert message.text is not None
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.")
        return

    fio = message.text.strip()

    if len(fio) < 5:
        await logger.awarning(
            "registration_failed",
            telegram_id=message.from_user.id if message.from_user else None,
            reason="invalid_fio",
        )
        await message.answer("❌ Введите полное ФИО.")
        return

    await state.clear()
    assert message.from_user is not None
    # Сохраняем в памяти
    pending_registrations[message.from_user.id] = fio

    # Уведомляем админа
    from src.bot.setup import get_bot

    bot = get_bot()

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять", callback_data=f"reg_accept:{message.from_user.id}")
    builder.button(text="❌ Отклонить", callback_data=f"reg_decline:{message.from_user.id}")
    builder.adjust(2)

    await bot.send_message(
        chat_id=SUPER_ADMIN_TG_ID,
        text=f"📋 <b>Новая заявка на регистрацию</b>\n\n"
        f"👤 ФИО: <b>{fio}</b>\n"
        f"🆔 Telegram ID: <code>{message.from_user.id}</code>\n"
        f"👤 Username: @{message.from_user.username or 'не указан'}",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )

    await message.answer("✅ Заявка отправлена администратору.\nОжидайте подтверждения.")


@router.callback_query(F.data.startswith("reg_accept:"))
async def registration_accept(callback: CallbackQuery):
    if callback.data is None:
        return

    if not isinstance(callback.message, Message):
        return
    _, tg_id = callback.data.split(":")
    tg_id = int(tg_id)

    fio = pending_registrations.pop(tg_id, None)  # берём и удаляем

    if not fio:
        await logger.awarning(
            "registration_failed",
            telegram_id=tg_id,
            reason="request_not_found",
        )
        await callback.answer("⚠️ Заявка не найдена или устарела.")
        return

    # ✅ Исправление — использовать uow.users.create()
    async with UnitOfWork(get_session_maker()) as uow:
        existing = await uow.users.get_by_telegram_id(tg_id)
        if existing:
            await logger.awarning(
                "registration_failed",
                telegram_id=tg_id,
                reason="already_registered",
            )
            await callback.answer("⚠️ Пользователь уже зарегистрирован.")
            text = callback.message.text or ""
            await callback.message.edit_text(text + "\n\n⚠️ Уже зарегистрирован.")
            return

        new_user = UserModel(
            username=fio,
            password_hash="bot_registration",
            role="user",
            is_active=True,
            telegram_id=tg_id,
        )
        await uow.users.create(new_user)  # ← через репозиторий
        await logger.ainfo("user_registered", telegram_id=tg_id)

    # Уведомляем юзера
    from src.bot.setup import get_bot

    bot = get_bot()
    await bot.send_message(
        chat_id=tg_id,
        text="✅ Ваша заявка одобрена!\nНапишите /start чтобы начать работу.",
    )

    await callback.answer("✅ Пользователь принят.")
    text = callback.message.text or ""
    await callback.message.edit_text(text + "\n\n✅ Принят. Пользователь создан.")


@router.callback_query(F.data.startswith("reg_decline:"))
async def registration_decline(callback: CallbackQuery):
    if callback.data is None:
        return
    if not isinstance(callback.message, Message):
        return

    _, tg_id = callback.data.split(":")
    tg_id = int(tg_id)
    await logger.awarning(
        "registration_failed",
        telegram_id=tg_id,
        reason="declined",
    )

    from src.bot.setup import get_bot

    bot = get_bot()
    await bot.send_message(chat_id=tg_id, text="❌ Ваша заявка отклонена.\nОбратитесь к администратору.")

    await callback.answer("❌ Заявка отклонена.")
    text = callback.message.text or ""
    await callback.message.edit_text(text + "\n\n❌ Отклонено.")
