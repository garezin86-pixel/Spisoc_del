# src/utils/ics.py
"""
Генерация iCalendar (.ics) фида дедлайнов — RFC 5545, минимально
необходимое подмножество: VCALENDAR с набором VEVENT, по одному на задачу
с дедлайном. Никаких внешних библиотек — формат достаточно прост, а лишняя
зависимость ради десятка строк текста того не стоит.
"""

import re
from datetime import datetime, timedelta, timezone

from src.models.task import SpisokModel

# Длительность события в календаре — дедлайн это точка во времени, а не
# диапазон, но события нулевой длины некоторые календарные клиенты
# отображают неудобно (сливаются в точку на шкале). 30 минут — компромисс:
# заметно на дневном виде, не выглядит как "встреча на полчаса".
EVENT_DURATION = timedelta(minutes=30)


def _escape_ics_text(value: str) -> str:
    """Экранирует спецсимволы по RFC 5545 (запятая, точка с запятой, бэкслеш, перенос строки)."""
    value = value.replace("\\", "\\\\")
    value = value.replace(";", "\\;")
    value = value.replace(",", "\\,")
    value = value.replace("\n", "\\n").replace("\r", "")
    return value


def _fold_line(line: str) -> str:
    """
    RFC 5545 требует "складывать" строки длиннее 75 октетов — продолжение
    начинается с пробела. Без этого некоторые парсеры (в т.ч. старые
    версии Outlook) обрезают длинные SUMMARY/DESCRIPTION.
    """
    if len(line.encode("utf-8")) <= 75:
        return line
    out = []
    while len(line.encode("utf-8")) > 75:
        # Режем по символам, а не байтам, чтобы не разрезать многобайтовый
        # UTF-8 символ пополам — берём с запасом (75 байт почти всегда
        # больше 75 символов кириллицы в UTF-8, поэтому 70 символов как
        # консервативная граница безопасна).
        cut = 70
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return "\r\n".join(out)


def _format_dt_utc(dt: datetime) -> str:
    """DTSTART/DTEND в UTC с суффиксом Z — календарь сам переведёт в локальное время пользователя."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sanitize_uid_part(value: str) -> str:
    """UID должен быть стабильным ASCII-идентификатором — вычищаем всё, кроме безопасных символов."""
    return re.sub(r"[^a-zA-Z0-9._-]", "", value) or "task"


def build_ics_feed(tasks: list[SpisokModel], calendar_name: str = "Spisok Del — дедлайны") -> str:
    """
    Собирает .ics-фид из задач с указанным дедлайном. Задачи без дедлайна
    вызывающий код должен отфильтровать заранее — здесь для простоты нет
    дополнительной проверки on top (single responsibility: это чисто
    сериализация, а не бизнес-логика выбора задач).
    """
    now_stamp = _format_dt_utc(datetime.now(timezone.utc))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Spisok Del//Calendar Feed//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_ics_text(calendar_name)}",
        # Подсказка клиентам, как часто перечитывать фид (поддерживается не
        # всеми, но Google Calendar и Outlook её уважают) — раз в час
        # достаточно для дедлайнов задач, не нужно чаще.
        "X-PUBLISHED-TTL:PT1H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
    ]

    for task in tasks:
        if not task.deadline:
            continue

        uid = f"task-{task.id}@spisok-del.{_sanitize_uid_part(str(task.id))}"
        dtstart = _format_dt_utc(task.deadline)
        dtend = _format_dt_utc(task.deadline + EVENT_DURATION)
        summary = _escape_ics_text(task.title or f"Задача №{task.id}")

        description_parts = []
        if task.description:
            description_parts.append(task.description)
        status_label = {
            "backlog": "В очереди",
            "todo": "Новая",
            "in_progress": "В работе",
            "review": "На проверке",
            "done": "Готово",
        }.get(task.status, task.status)
        description_parts.append(f"Статус: {status_label}")
        description = _escape_ics_text("\\n".join(description_parts))

        lines.append("BEGIN:VEVENT")
        lines.append(_fold_line(f"UID:{uid}"))
        lines.append(f"DTSTAMP:{now_stamp}")
        lines.append(f"DTSTART:{dtstart}")
        lines.append(f"DTEND:{dtend}")
        lines.append(_fold_line(f"SUMMARY:{summary}"))
        if description:
            lines.append(_fold_line(f"DESCRIPTION:{description}"))
        # BUSY у выполненных задач не нужен — они уже не требуют внимания,
        # но остаются видимыми в календаре (историчность), просто без
        # "занятости" во free/busy-запросах других приложений.
        lines.append(f"TRANSP:{'TRANSPARENT' if task.status == 'done' else 'OPAQUE'}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    # RFC 5545 требует CRLF в качестве разделителя строк.
    return "\r\n".join(lines) + "\r\n"
