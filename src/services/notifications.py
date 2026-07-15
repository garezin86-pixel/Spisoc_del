from typing import Optional

import structlog

from src.bot.keyboards.notification_keyboard import task_action_keyboard
from src.bot.setup import get_bot
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.notification_log import NotificationLogModel
from src.utils.datetime_utils import to_local

logger = structlog.get_logger()


async def notify_comment_added(comment_id: int):
    """Фоновая отправка уведомления о новом комментарии."""
    session_maker = get_session_maker()
    async with UnitOfWork(session_maker) as uow:
        bot = get_bot()
        comment = await uow.notifications.get_comment_with_relations(comment_id)
        if not comment:
            return

        task = comment.task
        commenter = comment.user
        notify_recipients = {}

        if task.author and task.author.telegram_id:
            notify_recipients[task.author.telegram_id] = task.author.id
        if task.user and task.user.telegram_id:
            notify_recipients[task.user.telegram_id] = task.user.id
        if commenter and commenter.telegram_id:
            notify_recipients.pop(commenter.telegram_id, None)

        if not notify_recipients:
            return

        text = f"💬 Новый комментарий!\n\n📋 Задача№ {task.id}\n📋 {task.title}\n💭 Комментарий: \n {comment.content}"

        for tg_id, user_id in notify_recipients.items():
            try:
                await bot.send_message(chat_id=tg_id, text=text)
                await logger.ainfo(
                    "notification_sent",
                    user_id=user_id,
                    type="comment_added",
                    task_id=task.id,
                )
            except Exception as e:
                await logger.aerror(
                    "notification_failed",
                    user_id=user_id,
                    error=str(e),
                )
                logger.error(f"Ошибка отправки уведомления комментария {comment.id}: {e}")


async def notify_task_assigned(task_id: int):
    """Фоновая отправка уведомления о назначении задачи (пользователю или группе)."""
    session_maker = get_session_maker()
    async with UnitOfWork(session_maker) as uow:
        bot = get_bot()
        task = await uow.notifications.get_task_with_relations(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found for notification")
            return

        sent_count = 0

        # Уведомление конкретному пользователю
        if task.user:
            # Не отправляем уведомление автору задачи
            if task.user_id == task.author_id:
                logger.info(f"Task {task_id}: author is executor, skip notification")
                return

            text = (
                "📌 <b>Вам назначена новая задача</b>\n\n"
                f"📋 <b>ID:</b> {task.id}\n"
                f"📋 <b>Название:</b> {task.title}\n"
                f"📅 <b>Дедлайн:</b> {to_local(task.deadline) if task.deadline else 'не указан'}"
            )

            if task.description:
                text += f"\n📝 <b>Описание:</b> {task.description[:200]}"

            success = True
            error = None
            # Telegram-часть работает, только если у пользователя привязан
            # telegram_id — раньше вся ветка (включая push ниже) требовала
            # этого, из-за чего пользователь, подписанный ТОЛЬКО на веб-push
            # (без Telegram), не получал вообще ничего. Теперь push
            # отправляется независимо от наличия telegram_id.
            if task.user.telegram_id:
                try:
                    await bot.send_message(
                        chat_id=task.user.telegram_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=task_action_keyboard(task.id),
                    )
                    sent_count += 1
                    logger.info(
                        "notification_sent",
                        user_id=task.user_id,
                        type="task_assigned",
                        task_id=task.id,
                    )
                except Exception as e:
                    await logger.aerror(
                        "notification_failed",
                        user_id=task.user_id,
                        error=str(e),
                    )
                    logger.error(f"Failed to send task notification to user {task.user_id}: {e}")
                    success = False
                    error = str(e)[:500]

                # ✅ Лог пишется всегда — и при успехе, и при ошибке
                log = NotificationLogModel(
                    user_id=task.user_id,
                    notification_type="task_assigned",
                    task_id=task.id,
                    content=text,
                    success=success,
                    error=error,
                )
                uow.session.add(log)
                await uow.commit()

            # Веб-push — независимый канал поверх Telegram: если у пользователя
            # есть активные подписки браузера (см. push_subscriptions), они
            # получат уведомление даже с закрытой вкладкой Telegram, а если
            # Telegram вообще не привязан — push может быть единственным каналом.
            from src.repositories.push_repository import PushRepository
            from src.services.push_service import send_push_to_user

            await send_push_to_user(
                PushRepository(uow.session),
                task.user.id,  # не task.user_id — та колонка типизирована как int | None (nullable FK);
                # task.user здесь уже точно не None (проверено выше), а у самого
                # объекта пользователя id — обычный int, без Optional.
                title="Новая задача",
                body=task.title,
                url=f"/tasks/{task.id}",
            )

        # Уведомление группе
        elif task.group:
            logger.info(f"Sending group notification for task {task.id} to group {task.group.id}")

            users = await uow.groups.get_group_users_with_telegram(
                group_id=task.group.id, exclude_user_id=task.author_id
            )

            if not users:
                logger.info(f"No users with telegram in group {task.group.id}")
                return

            user_ids = [user.id for user in users]
            settings_map = await uow.notification_settings.get_by_user_ids(user_ids)

            for user in users:
                if not user.telegram_id:
                    continue

                settings = settings_map.get(user.id)
                if settings and not getattr(settings, "notify_task_assigned", True):
                    logger.info(f"User {user.id} disabled task notifications")
                    continue

                # ВАЖНО: тип должен совпадать с тем, что реально пишется в лог ниже
                # ("group_task_assigned"), иначе проверка никогда не находит совпадение
                # и группе шлётся повторное уведомление на каждый вызов.
                if await _already_sent_within(uow, user.id, task.id, "group_task_assigned", hours=1):
                    logger.info(f"Notification already sent to user {user.id} for task {task.id}")
                    continue

                text = (
                    "👥 <b>Вашей группе назначена новая задача</b>\n\n"
                    f"📋 <b>ID:</b> {task.id}\n"
                    f"📋 <b>Название:</b> {task.title}\n"
                    f"📅 <b>Дедлайн:</b> {to_local(task.deadline) if task.deadline else 'не указан'}\n\n"
                    f"👤 <b>Автор:</b> {task.author.username if task.author else 'Неизвестен'}"
                )

                if task.description:
                    text += f"\n📝 <b>Описание:</b> {task.description[:200]}"

                success = True
                error = None
                try:
                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=task_action_keyboard(task.id),
                    )
                    sent_count += 1
                    logger.info(
                        "notification_sent",
                        user_id=user.id,
                        type="group_task_assigned",
                        task_id=task.id,
                    )
                except Exception as e:
                    await logger.aerror(
                        "notification_failed",
                        user_id=user.id,
                        error=str(e),
                    )
                    logger.error(f"Failed to send group notification to user {user.id}: {e}")
                    success = False
                    error = str(e)[:500]

                log = NotificationLogModel(
                    user_id=user.id,
                    notification_type="group_task_assigned",
                    task_id=task.id,
                    content=text,
                    success=success,
                    error=error,
                )
                uow.session.add(log)

            await uow.commit()

        logger.info(f"Task {task_id} notification completed. Sent: {sent_count}")


# Вспомогательная функция для дедупликации
async def _already_sent_within(uow, user_id: int, task_id: int | None, notif_type: str, hours: int) -> bool:
    """Проверяет через репозиторий, было ли уведомление отправлено за последние hours часов."""
    return await uow.notifications.check_already_sent(
        user_id=user_id,
        task_id=task_id,
        notification_type=notif_type,
        hours_back=hours,
    )


async def notify_task_updated(task_id: int | None, changed_fields: dict, editor_telegram_id: Optional[int] = None):
    """Фоновая отправка уведомления об изменении задачи текущему исполнителю."""
    if task_id is None:
        logger.error("task_id is None")
        return

    session_maker = get_session_maker()
    async with UnitOfWork(session_maker) as uow:
        bot = get_bot()
        task = await uow.notifications.get_task_with_relations(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found")
            return

        # ✅ Собираем получателей как список кортежей (telegram_id, user_id)
        recipients = []  # [(telegram_id, user_id), ...]

        if task.user and task.user.telegram_id:
            if task.user.telegram_id != editor_telegram_id:
                recipients.append((task.user.telegram_id, task.user.id))
        elif task.group:
            users = await uow.groups.get_group_users_with_telegram(
                group_id=task.group.id, exclude_user_id=editor_telegram_id
            )
            # ✅ Сразу берем и telegram_id, и user_id
            recipients = [(user.telegram_id, user.id) for user in users if user.telegram_id]
        else:
            logger.warning(f"No recipients for task {task_id}")
            return

        if not recipients:
            logger.warning(f"No valid recipients for task {task_id}")
            return

        # Формируем сообщение
        lines = [
            "✏️ <b>Ваша задача была изменена</b>\n",
            f"📋 ID: {task.id}\n",
            f"📋 Название: {task.title}\n",
        ]

        field_labels = {
            "title": ("📝 Название", lambda v: v),
            "description": ("📄 Описание", lambda v: v or "—"),
            "deadline": ("📅 Дедлайн", lambda v: to_local(v) if v else "Удалён"),
            "status": (
                "✅ Статус",
                lambda v: {
                    "done": "Выполнено",
                    "in_progress": "В работе",
                    "review": "На проверке",
                    "todo": "Новая",
                    "backlog": "В очереди",
                }.get(v, v),
            ),
            "user_id": ("👤 Исполнитель", lambda v: "изменён"),
            "group_id": ("👥 Группа", lambda v: "изменена"),
        }

        for field, new_value in changed_fields.items():
            if field in field_labels:
                label, formatter = field_labels[field]
                lines.append(f"{label}: {formatter(new_value)}")

        if len(lines) == 3:
            logger.info(f"No meaningful changes for task {task_id}")
            return

        text = "\n".join(lines)

        # ✅ Отправляем уведомления, используя оба значения из кортежа
        for telegram_id, user_id in recipients:
            try:
                await bot.send_message(
                    chat_id=telegram_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=task_action_keyboard(task.id),
                )
                logger.info(f"Task update notification sent to {telegram_id} for task {task_id}")
                await logger.ainfo(
                    "notification_sent",
                    user_id=user_id,
                    type="task_updated",
                    task_id=task.id,
                )

                # ✅ Логируем успешную отправку (user_id уже есть)
                log = NotificationLogModel(
                    user_id=user_id,
                    notification_type="task_updated",
                    task_id=task.id,
                    content=text[:2000],
                    success=True,
                    error=None,
                )
                uow.session.add(log)

            except Exception as e:
                error_msg = str(e)[:500]
                logger.error(f"Ошибка отправки уведомления telegram_id={telegram_id}: {error_msg}")
                await logger.aerror(
                    "notification_failed",
                    user_id=user_id,
                    error=error_msg,
                )

                # ✅ Логируем неудачную отправку
                log = NotificationLogModel(
                    user_id=user_id,
                    notification_type="task_updated",
                    task_id=task.id,
                    content=text[:2000],
                    success=False,
                    error=error_msg,
                )
                uow.session.add(log)

        # ✅ Один коммит для всех логов
        await uow.commit()
