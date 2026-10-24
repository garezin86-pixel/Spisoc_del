# src/services/client_import_service.py
"""Импорт клиентов из CSV/XLSX: сопоставление колонок, предпросмотр, создание.

Файл читаем теми же функциями, что и импорт задач (кодировки cp1251/utf-8, разделитель «,» или «;», .xlsx).
Дальше всё здесь: колонки файла сопоставляются с полями клиента (автоподсказка по заголовкам, пользователь
может поправить), каждая строка проверяется той же схемой ClientCreate, что и создание из интерфейса,
дубликаты пропускаются. `dry_run=True` ничего не пишет и отдаёт тот же отчёт — это и есть предпросмотр.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import structlog
from pydantic import ValidationError

from src.models.client import ClientModel
from src.models.user import UserModel, UserRole
from src.repositories.client_repository import ClientRepository
from src.repositories.users_repository import UserRepository
from src.schemas.client import ClientCreate
from src.services.task_import_service import TaskImportParseError, _rows_from_csv, _rows_from_xlsx

logger = structlog.get_logger()

MAX_IMPORT_ROWS = 5000
MAX_FILE_BYTES = 5 * 1024 * 1024
PREVIEW_ROWS = 10

# Поля клиента, в которые можно сопоставить колонку: ключ → подпись для интерфейса.
FIELD_LABELS: dict[str, str] = {
    "name": "Название / ФИО",
    "client_type": "Тип (компания / частное лицо)",
    "phone": "Телефон",
    "email": "Email",
    "address": "Адрес",
    "notes": "Заметки",
    "owner": "Ответственный (логин или имя)",
    "birth_date": "Дата рождения",
    "gender": "Пол",
    "next_contact_at": "Связаться снова",
}

# Заголовки (в нижнем регистре), по которым колонка угадывается автоматически.
HEADER_ALIASES: dict[str, set[str]] = {
    "name": {
        "название",
        "наименование",
        "имя",
        "фио",
        "клиент",
        "компания",
        "контрагент",
        "организация",
        "name",
        "company",
        "client",
        "full name",
        "customer",
    },
    "client_type": {"тип", "тип клиента", "вид", "type", "client type"},
    "phone": {"телефон", "тел", "тел.", "мобильный", "номер телефона", "phone", "mobile", "tel"},
    "email": {"email", "e-mail", "почта", "эл. почта", "электронная почта", "mail"},
    "address": {"адрес", "address", "город", "city"},
    "notes": {"заметки", "заметка", "примечание", "примечания", "комментарий", "notes", "comment", "comments"},
    "owner": {"ответственный", "менеджер", "владелец", "owner", "manager", "responsible"},
    "birth_date": {"дата рождения", "день рождения", "др", "birth date", "birthday", "birthdate"},
    "gender": {"пол", "gender", "sex"},
    "next_contact_at": {"следующий контакт", "связаться", "связаться снова", "дата контакта", "next contact"},
}

NAME_WORDS = {
    "фио",
    "название",
    "наименование",
    "имя",
    "клиент",
    "компания",
    "контрагент",
    "организация",
    "name",
    "company",
    "client",
    "customer",
}
_TYPE_TITLE = {"company": "компания", "person": "частное лицо"}
_COMPANY_WORDS = {"компания", "юрлицо", "юр. лицо", "юридическое лицо", "организация", "company", "b2b", "legal"}
_PERSON_WORDS = {"частное лицо", "физлицо", "физ. лицо", "физическое лицо", "человек", "person", "b2c", "individual"}
_MALE = {"м", "муж", "мужской", "мужчина", "male", "m"}
_FEMALE = {"ж", "жен", "женский", "женщина", "female", "f"}
_DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y")


class ClientImportError(Exception):
    """Файл или параметры импорта не годятся целиком (формат, кодировка, нет колонки с названием и т.п.)."""


# ── чтение файла ─────────────────────────────────────────────────────────────
def read_table(filename: str, content: bytes) -> tuple[list[Any], list[list[Any]]]:
    """Возвращает (строка заголовков, остальные строки). Пустые строки отбрасываются."""
    if len(content) > MAX_FILE_BYTES:
        raise ClientImportError(f"Файл слишком большой (максимум {MAX_FILE_BYTES // (1024 * 1024)} МБ)")
    name = (filename or "").lower()
    try:
        if name.endswith(".xlsx"):
            header, rows = _rows_from_xlsx(content)
        elif name.endswith(".csv"):
            header, rows = _rows_from_csv(content)
        else:
            raise ClientImportError("Поддерживаются только файлы .csv и .xlsx")
    except TaskImportParseError as exc:
        raise ClientImportError(str(exc)) from exc

    rows = [r for r in rows if any(str(cell).strip() for cell in r if cell is not None)]
    if len(rows) > MAX_IMPORT_ROWS:
        raise ClientImportError(f"Слишком много строк ({len(rows)}), максимум {MAX_IMPORT_ROWS} за один импорт")
    return header, rows


def _header_text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def suggest_mapping(header: list[Any]) -> dict[str, int]:
    """Поле клиента → индекс колонки по заголовкам. Каждая колонка и каждое поле — не более одного раза."""
    mapping: dict[str, int] = {}
    for index, raw in enumerate(header):
        title = _header_text(raw).lower()
        for field_key, aliases in HEADER_ALIASES.items():
            if field_key not in mapping and title in aliases:
                mapping[field_key] = index
                break
    if "name" not in mapping:
        # «ФИО / Компания», «Название компании», «Имя клиента»: название — единственное обязательное поле, а заголовки
        # у него самые разные, поэтому ищем по отдельным словам. Остальные поля так не угадываем: «Адрес эл. почты»
        # иначе превратился бы в адрес.
        used = set(mapping.values())
        for index, raw in enumerate(header):
            words = set(re.findall(r"[a-zа-яё]+", _header_text(raw).lower()))
            if index not in used and words & NAME_WORDS:
                mapping["name"] = index
                break
    return mapping


def describe_columns(filename: str, content: bytes) -> dict[str, Any]:
    """Данные для окна сопоставления: колонки с примерами значений, подсказанное сопоставление, число строк."""
    header, rows = read_table(filename, content)
    suggested = suggest_mapping(header)
    by_index = {index: key for key, index in suggested.items()}
    columns = []
    for index, raw in enumerate(header):
        samples = [_cell_text(r[index]) for r in rows[:3] if index < len(r) and _cell_text(r[index])]
        columns.append(
            {
                "index": index,
                "header": _header_text(raw) or f"Колонка {index + 1}",
                "suggested": by_index.get(index),
                "samples": samples,
            }
        )
    return {
        "columns": columns,
        "fields": [{"key": key, "label": label, "required": key == "name"} for key, label in FIELD_LABELS.items()],
        "total_rows": len(rows),
    }


# ── разбор значений ──────────────────────────────────────────────────────────
def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, float) and value.is_integer():  # Excel хранит номера как 380987654321.0
        return str(int(value))
    return str(value).strip()


_LEGAL_FORM = re.compile(
    r"(?<!\w)(ооо|тов|чп|фоп|ип|ао|пао|зао|оао|нко|тд|гк|llc|ltd|inc|gmbh|corp)(?!\w)", re.IGNORECASE
)
_PERSON_WORD = re.compile(r"^[A-ZА-ЯЁІЇЄҐ][a-zа-яёіїєґ'’]+(?:-[A-ZА-ЯЁІЇЄҐ]?[a-zа-яёіїєґ'’]+)*$")


def infer_client_type(name: str) -> str:
    """Угадать тип по названию: «ООО Ромашка», кавычки, цифры — компания; «Иванов Иван Петрович» — человек.

    Это эвристика: «Альфа Строй» без оргформы будет принят за человека, поэтому в интерфейсе она включается
    отдельным выбором («Определять по названию»), а не по умолчанию.
    """
    text = name.strip()
    if _LEGAL_FORM.search(text) or any(ch in text for ch in '«»"') or any(ch.isdigit() for ch in text):
        return "company"
    words = text.split()
    if 2 <= len(words) <= 4 and all(_PERSON_WORD.match(w) for w in words):
        return "person"
    return "company"


def _parse_type(raw: str, default: str, name: str = "") -> tuple[str, str | None]:
    """Тип клиента из колонки; `default` — company, person или auto (угадывать по названию)."""
    key = raw.strip().lower()
    if key in _COMPANY_WORDS:
        return "company", None
    if key in _PERSON_WORDS:
        return "person", None
    if default == "auto":
        guessed = infer_client_type(name)
        if not key:
            return guessed, None
        return guessed, f"тип «{raw}» не распознан, определён по названию: «{_TYPE_TITLE[guessed]}»"
    if not key:
        return default, None
    return default, f"тип «{raw}» не распознан, поставлен «{_TYPE_TITLE[default]}»"


def _parse_gender(raw: str) -> tuple[str | None, str | None]:
    key = raw.strip().lower().rstrip(".")
    if not key:
        return None, None
    if key in _MALE:
        return "male", None
    if key in _FEMALE:
        return "female", None
    return None, f"пол «{raw}» не распознан, оставлен пустым"


def _parse_date(raw: Any) -> tuple[date | None, str | None]:
    if raw is None or _cell_text(raw) == "":
        return None, None
    if isinstance(raw, datetime):
        return raw.date(), None
    if isinstance(raw, date):
        return raw, None
    text = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), None
        except ValueError:
            continue
    return None, f"дата «{text}» не распознана, оставлена пустой"


def phone_key(phone: str | None) -> str | None:
    """Ключ для сравнения телефонов: последние 10 цифр (+380 98 765-43-21 и 098 765 43 21 — один номер)."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 7:
        return None
    return digits[-10:]


def email_key(email: str | None) -> str | None:
    value = (email or "").strip().lower()
    return value or None


def name_key(name: str, client_type: str) -> tuple[str, str]:
    return (" ".join(name.lower().split()), client_type)


# ── отчёт ────────────────────────────────────────────────────────────────────
@dataclass
class RowIssue:
    row: int
    message: str


@dataclass
class ImportPreviewRow:
    row: int
    name: str
    client_type: str
    phone: str | None
    email: str | None


@dataclass
class ImportReport:
    dry_run: bool
    default_type: str = "company"  # какое значение «Тип, если не указан» дошло до сервера — видно в отчёте
    total_rows: int = 0
    to_create: int = 0  # сколько строк годятся (при dry_run ещё не создано)
    created: int = 0
    skipped_duplicates: int = 0
    errors: list[RowIssue] = field(default_factory=list)
    warnings: list[RowIssue] = field(default_factory=list)
    duplicates: list[RowIssue] = field(default_factory=list)
    preview: list[ImportPreviewRow] = field(default_factory=list)


@dataclass
class _ValidRow:
    row: int
    data: ClientCreate
    owner_id: int | None


class ClientImportService:
    def __init__(self, client_repo: ClientRepository, user_repo: UserRepository):
        self.client_repo = client_repo
        self.user_repo = user_repo

    async def _owners(self) -> dict[str, int]:
        """Логин и имя пользователя (в нижнем регистре) → id, только в своей компании."""
        owners: dict[str, int] = {}
        for user in await self.user_repo.get_all():
            owners[(user.username or "").lower()] = user.id
            if user.login:
                owners.setdefault(user.login.lower(), user.id)
        return owners

    async def import_clients(
        self,
        *,
        filename: str,
        content: bytes,
        mapping: dict[str, int],
        current_user: UserModel,
        default_type: str = "company",
        skip_duplicates: bool = True,
        dry_run: bool = False,
    ) -> ImportReport:
        if current_user.role not in (UserRole.admin, UserRole.manager):
            from fastapi import HTTPException

            raise HTTPException(403, "Импортировать клиентов могут admin и manager")
        if default_type not in ("company", "person", "auto"):
            raise ClientImportError("Тип по умолчанию — company, person или auto")
        if "name" not in mapping:
            raise ClientImportError("Не выбрана колонка с названием клиента")
        unknown = set(mapping) - set(FIELD_LABELS)
        if unknown:
            raise ClientImportError(f"Неизвестные поля: {', '.join(sorted(unknown))}")
        if len(set(mapping.values())) != len(mapping):
            raise ClientImportError("Одна колонка выбрана для нескольких полей")

        header, rows = read_table(filename, content)
        if any(not isinstance(i, int) or i < 0 or i >= len(header) for i in mapping.values()):
            raise ClientImportError("Выбрана колонка, которой нет в файле")

        report = ImportReport(dry_run=dry_run, default_type=default_type, total_rows=len(rows))
        owners = await self._owners() if "owner" in mapping else {}
        seen_phone, seen_email, seen_name = await self._existing_keys()

        valid: list[_ValidRow] = []
        for offset, raw_row in enumerate(rows):
            row_number = offset + 2  # строка 1 — заголовки

            def cell(key: str) -> Any:
                index = mapping.get(key)
                return raw_row[index] if index is not None and index < len(raw_row) else None

            name = _cell_text(cell("name"))
            if not name:
                report.errors.append(RowIssue(row_number, "пустое название — строка пропущена"))
                continue

            client_type, type_warning = _parse_type(_cell_text(cell("client_type")), default_type, name)
            if type_warning:
                report.warnings.append(RowIssue(row_number, type_warning))
            gender, gender_warning = _parse_gender(_cell_text(cell("gender")))
            if gender_warning:
                report.warnings.append(RowIssue(row_number, gender_warning))
            birth, birth_warning = _parse_date(cell("birth_date"))
            if birth_warning:
                report.warnings.append(RowIssue(row_number, birth_warning))
            next_contact, next_warning = _parse_date(cell("next_contact_at"))
            if next_warning:
                report.warnings.append(RowIssue(row_number, next_warning))

            if client_type != "person" and (birth is not None or gender is not None):
                report.warnings.append(
                    RowIssue(row_number, "дата рождения и пол есть только у частного лица — пропущены")
                )
                birth, gender = None, None

            owner_id: int | None = None
            owner_raw = _cell_text(cell("owner"))
            if owner_raw:
                owner_id = owners.get(owner_raw.lower())
                if owner_id is None:
                    report.warnings.append(
                        RowIssue(row_number, f"ответственный «{owner_raw}» не найден, назначен тот, кто импортирует")
                    )

            payload = {
                "name": name,
                "client_type": client_type,
                "phone": _cell_text(cell("phone")) or None,
                "email": _cell_text(cell("email")) or None,
                "address": _cell_text(cell("address")) or None,
                "notes": _cell_text(cell("notes")) or None,
                "birth_date": birth,
                "gender": gender,
                "next_contact_at": next_contact,
            }
            try:
                data = ClientCreate(**payload)
            except ValidationError as exc:
                message = "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())
                report.errors.append(RowIssue(row_number, f"{message} — строка пропущена"))
                continue

            reason = self._duplicate_reason(data, seen_phone, seen_email, seen_name)
            if reason is not None and skip_duplicates:
                report.skipped_duplicates += 1
                report.duplicates.append(RowIssue(row_number, f"«{data.name}»: {reason}"))
                continue
            self._remember(data, seen_phone, seen_email, seen_name)
            valid.append(_ValidRow(row_number, data, owner_id))

        report.to_create = len(valid)
        report.preview = [
            ImportPreviewRow(v.row, v.data.name, v.data.client_type, v.data.phone, v.data.email)
            for v in valid[:PREVIEW_ROWS]
        ]

        if dry_run or not valid:
            return report

        self.client_repo.set_audit_user(current_user.id)
        for item in valid:
            self.client_repo.session.add(
                ClientModel(
                    name=item.data.name,
                    client_type=item.data.client_type,
                    phone=item.data.phone,
                    email=item.data.email,
                    address=item.data.address,
                    notes=item.data.notes,
                    birth_date=item.data.birth_date,
                    gender=item.data.gender,
                    next_contact_at=item.data.next_contact_at,
                    owner_id=item.owner_id if item.owner_id is not None else current_user.id,
                )
            )
        await self.client_repo.session.commit()  # одна транзакция: либо все строки, либо ни одной
        report.created = len(valid)
        await logger.ainfo(
            "clients_imported", user_id=current_user.id, created=report.created, skipped=report.skipped_duplicates
        )
        return report

    # ── дубликаты ────────────────────────────────────────────────────────────
    async def _existing_keys(self) -> tuple[set[str], set[str], set[tuple[str, str]]]:
        phones: set[str] = set()
        emails: set[str] = set()
        names: set[tuple[str, str]] = set()
        for name, client_type, phone, email in await self.client_repo.list_dedup_fields():
            if (key := phone_key(phone)) is not None:
                phones.add(key)
            if (key := email_key(email)) is not None:
                emails.add(key)
            if not phone_key(phone) and not email_key(email):
                names.add(name_key(name, client_type))
        return phones, emails, names

    @staticmethod
    def _duplicate_reason(
        data: ClientCreate, phones: set[str], emails: set[str], names: set[tuple[str, str]]
    ) -> str | None:
        pk, ek = phone_key(data.phone), email_key(data.email)
        if pk is not None and pk in phones:
            return "такой телефон уже есть"
        if ek is not None and ek in emails:
            return "такой email уже есть"
        if pk is None and ek is None and name_key(data.name, data.client_type) in names:
            return "клиент с таким названием уже есть"
        return None

    @staticmethod
    def _remember(data: ClientCreate, phones: set[str], emails: set[str], names: set[tuple[str, str]]) -> None:
        pk, ek = phone_key(data.phone), email_key(data.email)
        if pk is not None:
            phones.add(pk)
        if ek is not None:
            emails.add(ek)
        if pk is None and ek is None:
            names.add(name_key(data.name, data.client_type))
