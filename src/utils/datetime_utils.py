from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Kyiv")  # или "Europe/Zaporozhye", "Europe/Kyiv"


def to_local(dt: datetime | None) -> str:
    if not dt:
        return "Без дедлайна"
    # если datetime без tzinfo — считаем что это UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M")


def to_local_datetime(dt: datetime | None, none_label: str = "-") -> str:
    """
    Универсальное форматирование даты/времени в локальном часовом поясе.
    В отличие от to_local (заточен под дедлайны задач — жёстко возвращает
    "Без дедлайна" для None), здесь подпись для отсутствующего значения
    настраиваемая — подходит для generic-полей в админке вроде created_at,
    last_used_at, last_triggered_at, где "Без дедлайна" было бы бессмысленно.
    """
    if not dt:
        return none_label
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M")


# import pytz
# LOCAL_TZ = pytz.timezone("Europe/Kiev")

# def to_local(dt):
#     if not dt:
#         return "Без дедлайна"
#     if dt.tzinfo is None:
#         dt = pytz.utc.localize(dt)
#     return dt.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M")
