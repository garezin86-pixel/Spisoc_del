from markupsafe import Markup


def active_badge(user) -> Markup:
    if user.is_active:
        return Markup(
            '<span style="background:#198754;color:#fff;padding:3px 10px; border-radius:10px;">Активен</span>'
        )
    return Markup('<span style="background:#dc3545;color:#fff;padding:3px 10px; border-radius:10px;">Отключён</span>')
