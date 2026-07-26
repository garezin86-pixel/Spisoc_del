# src/utils/mentions.py
"""
Парсинг @упоминаний в тексте комментариев.

Важный нюанс: username в этом проекте МОЖЕТ содержать пробелы и кириллицу
(см. _validate_username в src/schemas/user.py — разрешены буквы, цифры,
подчёркивание и пробел). Поэтому простой regex вида "@\\w+" не подходит:
он бы обрезал имя вида "Александр Александрович" на первом пробеле,
приняв упоминание за "@Александр" и не найдя (или найдя не того)
пользователя.

Вместо этого после каждого "@" жадно разворачиваем текст слово за словом
и на каждом шаге проверяем, не совпало ли накопленное с одним из реально
существующих usernames — оставляя самое длинное совпадение. Это даёт
корректный результат для «Александр Александрович» даже если существует
и отдельный пользователь просто «Александр»: длинное имя гарантированно
победит короткое благодаря порядку проверки (от короткого к длинному,
последнее найденное совпадение и есть самое длинное).
"""

import re
import string

# Разумный потолок на количество слов после "@", которые пробуем
# накопить — ограничивает объём работы независимо от длины комментария.
MAX_MENTION_WORDS = 6

_WORD_RE = re.compile(r"\S+")
_STRIP_CHARS = string.punctuation + " \t\n"


def find_mentioned_usernames(text: str, known_usernames: list[str]) -> list[str]:
    """
    Возвращает usernames (в исходном регистре, как переданы в known_usernames),
    на которые есть @упоминание в тексте — уникальные, в порядке появления.
    Сравнение регистронезависимое, результат — нет.
    """
    if not text or not known_usernames:
        return []

    lookup = {u.lower(): u for u in known_usernames}
    words = _WORD_RE.findall(text)

    result: list[str] = []
    seen_lower: set[str] = set()

    for i, word in enumerate(words):
        if not word.startswith("@") or len(word) < 2:
            continue

        candidate_words = [word[1:]] + words[i + 1 : i + MAX_MENTION_WORDS]
        best: str | None = None
        acc = ""
        for w in candidate_words:
            acc = f"{acc} {w}".strip()
            trimmed = acc.strip(_STRIP_CHARS)
            key = trimmed.lower()
            if key in lookup:
                best = lookup[key]  # перезаписываем — оставляем самое длинное совпадение

        if best is not None and best.lower() not in seen_lower:
            seen_lower.add(best.lower())
            result.append(best)

    return result
