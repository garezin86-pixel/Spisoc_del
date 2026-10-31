# src/services/crm_export_service.py
"""Экспорт клиентов и сделок в CSV.

Формат рассчитан на Excel с русской локалью: кодировка UTF-8 с BOM (без него кириллица превращается в «кракозябры»)
и разделитель «;» (с запятой Excel открывает всё в одну колонку). Наш импорт клиентов определяет разделитель сам,
а заголовки колонок клиентов совпадают с теми, что он распознаёт, — выгрузку можно загрузить обратно.

Выгружать могут admin и manager: это вся база клиентов разом. Строки читаются постранично, чтобы не держать в памяти
лишнего; потолок — MAX_EXPORT_ROWS.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from fastapi.responses import Response

from src.models.user import UserModel, UserRole
from src.repositories.client_repository import ClientRepository
from src.repositories.deal_repository import DealRepository
from src.repositories.users_repository import UserRepository

_STATUS_LABEL = {"active": "Активный", "inactive": "Неактивный", "blacklisted": "Чёрный список"}
CLIENT_HEADER = [
    "ID",
    "Название",
    "Тип",
    "Телефон",
    "Email",
    "Адрес",
    "Заметки",
    "Ответственный",
    "Дата рождения",
    "Пол",
    "Связаться снова",
    "Создан",
    "Статус",
]
DEAL_HEADER = [
    "ID",
    "Название",
    "Клиент",
    "Стадия",
    "Статус",
    "Сумма",
    "Валюта",
    "Ответственный",
    "Ожидаемое закрытие",
    "Закрыта",
    "Причина отказа",
    "Заметки",
    "Создана",
]

PAGE = 1000
MAX_EXPORT_ROWS = 50_000

_TYPE_LABEL = {"company": "Компания", "person": "Частное лицо"}
_GENDER_LABEL = {"male": "Мужской", "female": "Женский"}
_STAGE_KIND_LABEL = {"open": "В работе", "won": "Выиграна", "lost": "Проиграна"}
_NUMBER_LIKE = re.compile(r"^[+-]?[\d\s().,-]+$")


def safe_cell(value: Any) -> str:
    """Значение ячейки как текст, безопасный для Excel.

    Название, заметки и т.п. приходят от пользователей и из импортируемых файлов. Ячейка, начинающаяся с «=», «@»,
    табуляции или возврата каретки (а также «+»/«-», если это не похоже на число или телефон), в Excel
    выполняется как формула — перед такой ячейкой ставим апостроф.
    """
    if value is None:
        return ""
    text = str(value)
    if text[:1] in ("=", "@", "\t", "\r"):
        return "'" + text
    if text[:1] in ("+", "-") and not _NUMBER_LIKE.match(text):
        return "'" + text
    return text


def _date(value: date | datetime | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _amount(value: Decimal | None) -> str:
    return f"{value:.2f}" if value is not None else ""


async def _fetch_all(fetch: Callable[[int, int], Awaitable[tuple[list, int]]]) -> list:
    items: list = []
    offset = 0
    while len(items) < MAX_EXPORT_ROWS:
        batch, total = await fetch(offset, PAGE)
        items.extend(batch)
        offset += PAGE
        if not batch or offset >= total:
            break
    return items[:MAX_EXPORT_ROWS]


def csv_response(content: bytes, prefix: str) -> Response:
    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _to_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


class CrmExportService:
    def __init__(self, client_repo: ClientRepository, deal_repo: DealRepository, user_repo: UserRepository):
        self.client_repo = client_repo
        self.deal_repo = deal_repo
        self.user_repo = user_repo

    @staticmethod
    def _require_manager(user: UserModel) -> None:
        if user.role not in (UserRole.admin, UserRole.manager):
            raise HTTPException(403, "Выгружать клиентов и сделки могут admin и manager")

    async def _usernames(self) -> dict[int, str]:
        return {u.id: u.username for u in await self.user_repo.get_all()}

    async def clients_csv(
        self,
        current_user: UserModel,
        *,
        search: str | None = None,
        owner_id: int | None = None,
        client_type: str | None = None,
        contact_due: bool = False,
        status: str | None = None,
    ) -> bytes:
        self._require_manager(current_user)
        clients = await _fetch_all(
            lambda offset, limit: self.client_repo.list_clients(
                search, offset, limit, contact_due, owner_id, client_type, status
            )
        )
        users = await self._usernames()
        rows = [
            [
                str(c.id),
                safe_cell(c.name),
                _TYPE_LABEL.get(c.client_type, c.client_type),
                safe_cell(c.phone),
                safe_cell(c.email),
                safe_cell(c.address),
                safe_cell(c.notes),
                safe_cell(users.get(c.owner_id, "")),
                _date(c.birth_date),
                _GENDER_LABEL.get(c.gender or "", ""),
                _date(c.next_contact_at),
                _date(c.created_at),
                _STATUS_LABEL.get(c.status, c.status),
            ]
            for c in clients
        ]
        return _to_bytes(CLIENT_HEADER, rows)

    async def deals_csv(
        self,
        current_user: UserModel,
        *,
        stage_id: int | None = None,
        owner_id: int | None = None,
        client_id: int | None = None,
        client_type: str | None = None,
    ) -> bytes:
        self._require_manager(current_user)
        deals = await _fetch_all(
            lambda offset, limit: self.deal_repo.list_deals(offset, limit, client_id, stage_id, owner_id, client_type)
        )
        users = await self._usernames()
        client_names = await self.client_repo.get_names({d.client_id for d in deals})
        stages = await self.deal_repo.get_stages_by_ids({d.stage_id for d in deals})
        rows = []
        for d in deals:
            stage = stages.get(d.stage_id)
            rows.append(
                [
                    str(d.id),
                    safe_cell(d.title),
                    safe_cell(client_names.get(d.client_id, "")),
                    safe_cell(stage[0] if stage else ""),
                    _STAGE_KIND_LABEL.get(stage[1], "") if stage else "",
                    _amount(d.amount),
                    d.currency,
                    safe_cell(users.get(d.owner_id, "")),
                    _date(d.expected_close_date),
                    _date(d.closed_at),
                    safe_cell(d.lost_reason),
                    safe_cell(d.notes),
                    _date(d.created_at),
                ]
            )
        return _to_bytes(DEAL_HEADER, rows)
