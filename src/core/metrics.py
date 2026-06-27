from prometheus_client import Counter

# Задачи
tasks_created = Counter("tasks_created_total", "Всего создано задач")
tasks_deleted = Counter("tasks_deleted_total", "Всего удалено задач (soft)")
tasks_hard_deleted = Counter("tasks_hard_deleted_total", "Всего удалено навсегда")
tasks_restored = Counter("tasks_restored_total", "Всего восстановлено задач")
tasks_completed = Counter("tasks_completed_total", "Всего выполнено задач")

# Уведомления
notifications_sent = Counter("notifications_sent_total", "Отправлено уведомлений", ["type"])
notifications_failed = Counter("notifications_failed_total", "Ошибок при отправке", ["type"])

# Бот
bot_errors = Counter("bot_errors_total", "Ошибки бота", ["handler"])

# Пользователи
users_registered = Counter("users_registered_total", "Зарегистрировано пользователей")
