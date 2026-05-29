import zoneinfo

USER_TZ = zoneinfo.ZoneInfo("Europe/Kiev")


def fmt_dt(dt) -> str:
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
    return dt.astimezone(USER_TZ).strftime("%d.%m.%Y %H:%M")


def active_badge(user):
    if user.is_active:
        return '<span style="background:#198754;color:#fff;padding:3px 10px; border-radius:10px;">Активен</span>'
    return '<span style="background:#dc3545;color:#fff;padding:3px 10px; border-radius:10px;">Отключён</span>'
