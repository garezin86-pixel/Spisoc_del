# src/utils/html_strip.py
"""Убирает HTML-разметку (parse_mode="HTML" из телеграм-сообщений, см.
src/services/notifications.py) из текста уведомления перед показом в
колокольчике — там нужен обычный текст, а не <b>...</b>."""

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    without_tags = _TAG_RE.sub("", text)
    return html.unescape(without_tags).strip()
