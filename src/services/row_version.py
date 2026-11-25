# src/services/row_version.py
"""Токен версии строки (защита от одновременной правки): клиент присылает `updated_at`, который получил в
последнем ответе; если строку с тех пор меняли — 409. Сравнение с точностью до микросекунды и не зависит от
того, вернула ли база время с часовым поясом (PostgreSQL) или без него (SQLite)."""

from datetime import datetime, timezone

from fastapi import HTTPException


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def parse_version(token: str) -> datetime:
    try:
        return _utc_naive(datetime.fromisoformat(token.strip()))
    except ValueError:
        raise HTTPException(422, "Неверная версия: нужно значение updated_at из ответа сервера") from None


def require_current_version(current: datetime, token: str | None) -> None:
    """Без токена правка применяется как есть (последняя запись побеждает); с токеном — только к свежей строке."""
    if token is None:
        return
    if parse_version(token) != _utc_naive(current):
        raise HTTPException(409, "Строку уже изменили. Обновите данные и повторите правку")
