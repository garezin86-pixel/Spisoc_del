# src/services/value_coercion.py
"""Проверка и приведение значения к типу колонки (общее для своих полей и самостоятельных таблиц).

Типы: text, number, date, select, boolean и связи client, deal, user (id записи).
Значение None — очистка. Неверное значение — 422 с понятным текстом.
Правила едины везде, где пользователь вводит значение «своей» колонки: свои поля клиентов и сделок (этап 3) и
ячейки самостоятельных таблиц (этап 4).
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException

# Типы-связи (колонки самостоятельных таблиц): значение — id записи CRM или пользователя
LINK_KINDS = ("client", "deal", "user")
MAX_REF_ID = 2**31 - 1  # Integer в PostgreSQL

MAX_TEXT_LENGTH = 2000
MAX_NUMBER = Decimal(10) ** 14  # Numeric(18, 4): 14 цифр до запятой


def coerce_value(label: str, kind: str, options: Sequence[str] | None, raw: Any, noun: str = "Поле") -> Any:
    """Приводит `raw` к типу `kind`. Возвращает значение для БД (str, Decimal, date, bool) или None (очистка).

    label — название колонки для сообщений об ошибках; noun — «Поле» или «Колонка»."""
    if raw is None:
        return None
    where = f"{noun} «{label}»"
    if kind in LINK_KINDS:
        # Связь — целый id (число или строка из цифр). Существование записи проверяет сервис (у него есть доступ к БД).
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise HTTPException(422, f"{where}: нужен id записи")
        text = str(raw).strip()
        if not text:
            return None  # пустая строка очищает связь
        if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= MAX_REF_ID:
            raise HTTPException(422, f"{where}: нужен id записи")
        return int(text)
    if kind == "boolean":
        if not isinstance(raw, bool):
            raise HTTPException(422, f"{where}: нужно true или false")
        return raw
    if isinstance(raw, bool):  # True/False не годятся ни для чего, кроме флажка
        raise HTTPException(422, f"{where}: неверный тип значения")
    if kind == "number":
        try:
            number = Decimal(str(raw).strip())
        except (InvalidOperation, ValueError):
            raise HTTPException(422, f"{where}: нужно число") from None
        if not number.is_finite() or abs(number) >= MAX_NUMBER:
            raise HTTPException(422, f"{where}: число слишком большое")
        if number != number.quantize(Decimal("0.0001")):
            raise HTTPException(422, f"{where}: не больше 4 знаков после запятой")
        return number
    if not isinstance(raw, str):
        raise HTTPException(422, f"{where}: нужна строка")
    text = raw.strip()
    if kind == "date":
        if not text:
            return None
        try:
            if len(text) != 10:
                raise ValueError
            return date.fromisoformat(text)
        except ValueError:
            raise HTTPException(422, f"{where}: дата в формате ГГГГ-ММ-ДД") from None
    if not text:
        return None  # пустая строка очищает значение
    if kind == "select":
        if text not in (options or []):
            raise HTTPException(422, f"{where}: значение «{text}» нет в списке")
        return text
    if len(text) > MAX_TEXT_LENGTH:  # text
        raise HTTPException(422, f"{where}: не длиннее {MAX_TEXT_LENGTH} символов")
    return text
