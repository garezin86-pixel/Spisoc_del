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


# import pytz
# LOCAL_TZ = pytz.timezone("Europe/Kiev")

# def to_local(dt):
#     if not dt:
#         return "Без дедлайна"
#     if dt.tzinfo is None:
#         dt = pytz.utc.localize(dt)
#     return dt.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M")
