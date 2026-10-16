# src/ai/resolve.py
"""Поиск сущностей по словам пользователя: клиент, сотрудник, стадия воронки.

Голос и текст дают неточные названия: «Ромашка», «ООО Ромашка», «Петру» (дательный падеж), «в переговоры». Поиск
терпим к регистру, ё/е, юридической форме и окончаниям; при нескольких подходящих записях инструмент не угадывает,
а просит выбрать (Choose).
"""

import re
from typing import Any

from src.ai.context import AIContext
from src.models.client import ClientModel
from src.models.user import UserModel

MAX_OPTIONS = 5  # столько кнопок выбора показываем

# юридические формы, которые в названии клиента и в речи могут расходиться
_LEGAL_FORMS = {"ооо", "тов", "зао", "пао", "ао", "оао", "фоп", "ип", "чп", "llc", "ltd", "inc", "тзов"}

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya", "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
}  # fmt: skip


def norm(text: str) -> str:
    """Нижний регистр, ё→е, без кавычек и знаков препинания, одинарные пробелы."""
    text = (text or "").casefold().replace("ё", "е")
    text = re.sub(r"[\"'«»“”„`.,;:!?()\[\]{}]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def translit(text: str) -> str:
    """Кириллица → латиница: «Петр» и «petr» сравниваются как одно слово."""
    return "".join(_TRANSLIT.get(ch, ch) for ch in norm(text))


def _tokens(text: str) -> list[str]:
    return [t for t in norm(text).split(" ") if t]


def strip_legal_forms(text: str) -> str:
    """Название без «ООО/ТОВ/ФОП…»; регистр слов сохраняется (поиск в БД может быть чувствителен к регистру)."""
    return " ".join(t for t in text.split() if norm(t) not in _LEGAL_FORMS)


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def stem_match(a: str, b: str) -> bool:
    """Слова совпадают с точностью до окончания: «петру» ~ «петр», «ивану» ~ «иван»."""
    if not a or not b:
        return False
    if a == b:
        return True
    shortest = min(len(a), len(b))
    return shortest >= 3 and _common_prefix(a, b) >= max(3, shortest - 1)


def name_score(query: str, candidate: str) -> int:
    """0 — не подходит; больше — лучше: 4 точное, 3 начало, 2 вхождение, 1 совпадение основ слов."""
    q, c = norm(query), norm(candidate)
    if not q or not c:
        return 0
    if q == c:
        return 4
    if c.startswith(q) or q.startswith(c):
        return 3
    if q in c or c in q:
        return 2
    q_tokens, c_tokens = _tokens(q), _tokens(c)
    if q_tokens and all(any(stem_match(qt, ct) for ct in c_tokens) for qt in q_tokens):
        return 1
    return 0


# ── клиенты ──────────────────────────────────────────────────────────────────
async def find_clients(ctx: AIContext, query: str, limit: int = 10) -> list[ClientModel]:
    """Клиенты по названию/телефону/email. Если полная фраза ничего не дала — без юридической формы, затем по
    самому длинному слову. Лучшие совпадения первыми."""
    query = (query or "").strip()
    if not query:
        return []
    bare = strip_legal_forms(query)
    words = sorted({w for w in (bare or query).split() if len(norm(w)) >= 3}, key=len, reverse=True)
    attempts: list[str] = []
    for base in [query, bare, *words]:
        # Варианты регистра: ILIKE в SQLite не понимает кириллицу, а речь/LLM дают «ромашка» вместо «Ромашка»
        for variant in (base, base.capitalize(), base.title()):
            if variant and variant not in attempts:
                attempts.append(variant)

    found: list[ClientModel] = []
    for attempt in attempts:
        found, _ = await ctx.clients.get_clients(attempt, 0, limit)
        if found:
            break
    ranked = sorted(found, key=lambda c: (-max(name_score(query, c.name), name_score(bare, c.name)), c.name.casefold()))
    return ranked


def pick_unique(query: str, candidates: list[ClientModel]) -> ClientModel | None:
    """Единственное название, совпавшее с запросом точно (без регистра и юр. формы), — выбор без вопросов."""
    exact = [
        c
        for c in candidates
        if norm(c.name) == norm(query) or norm(strip_legal_forms(c.name)) == norm(strip_legal_forms(query))
    ]
    return exact[0] if len(exact) == 1 else None


# ── сотрудники ───────────────────────────────────────────────────────────────
async def find_users(ctx: AIContext, query: str) -> list[UserModel]:
    """Активные сотрудники компании, подходящие под «Петру» / «@petr» / «Пётр Иванов»."""
    query = (query or "").strip().lstrip("@")
    if not query:
        return []
    scored: list[tuple[int, UserModel]] = []
    for user in await ctx.users.get_all():
        if not user.is_active:
            continue
        names = [user.username, user.login or ""]
        best = 0
        for name in names:
            best = max(best, name_score(query, name), name_score(translit(query), translit(name)))
        if best:
            scored.append((best, user))
    scored.sort(key=lambda s: (-s[0], s[1].username.casefold()))
    top = scored[0][0] if scored else 0
    # точное/почти точное совпадение побеждает слабые: «Петр» не должен предлагать всех «Петровых»
    return [u for score, u in scored if score >= max(top - 1, 1)] if top >= 3 else [u for _, u in scored]


# ── общие помощники для результатов выбора ───────────────────────────────────
def options_of(items: list[Any], label) -> list[tuple[int, str]]:
    return [(item.id, label(item)) for item in items[:MAX_OPTIONS]]
