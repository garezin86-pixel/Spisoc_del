# src/utils/login_generator.py
"""
Генерация логина из ФИО и временного пароля — для автоматического
создания учётной записи при одобрении заявки в Telegram-боте (см.
src/bot/handlers/registration.py).

username при этом НЕ трогаем — он остаётся полным ФИО и используется везде
в интерфейсе как отображаемое имя. login — отдельный, короткий,
транслитерированный идентификатор специально для входа и @упоминаний.
"""

import secrets
import string

# Стандартная практическая транслитерация (не ГОСТ, а читаемая на глаз) —
# для логина важнее короткая узнаваемая форма, чем формальная точность.
_TRANSLIT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}  # fmt: skip

# Символы, которые легко перепутать при чтении/ручном вводе (0/O, 1/l/I) —
# исключаем из алфавита временного пароля, раз его читают глазами из чата.
_PASSWORD_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")


def _transliterate_word(word: str) -> str:
    """Транслитерирует одно слово в нижний регистр латиницы, отбрасывая всё, что не буква/цифра."""
    result = []
    for ch in word.lower():
        if ch in _TRANSLIT_MAP:
            result.append(_TRANSLIT_MAP[ch])
        elif ch.isalnum() and ord(ch) < 128:
            result.append(ch)
        # прочие символы (пунктуация, эмодзи и т.п.) просто пропускаем
    return "".join(result)


def build_login_base(fio: str) -> str:
    """
    Строит базовый логин из ФИО вида "Фамилия Имя Отчество":
    фамилия + инициал имени, например "Иванов Иван Иванович" -> "ivanov.i".
    Если слов меньше двух (ФИО введено не полностью) — используется то,
    что есть. Если после транслитерации не осталось ни одного символа
    (например, ФИО состояло только из эмодзи) — возвращает "user" как
    безопасный фолбэк, а не пустую строку.
    """
    parts = [p for p in fio.strip().split() if p]
    if not parts:
        return "user"

    surname = _transliterate_word(parts[0])
    if len(parts) >= 2:
        name_initial = _transliterate_word(parts[1])[:1]
        base = f"{surname}.{name_initial}" if name_initial else surname
    else:
        base = surname

    return base or "user"


def generate_temp_password(length: int = 12) -> str:
    """Случайный пароль без визуально неоднозначных символов — его читают глазами из сообщения в Telegram."""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
