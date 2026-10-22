# src/ai/types.py
"""Типы результатов инструментов и ожидающего действия.

Все типы сериализуются в обычные dict/list (JSON), чтобы транспорт (FSM бота, Redis, ответ API) мог хранить
«ожидающее подтверждения действие» между сообщениями пользователя.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """Вызов инструмента, как его вернула LLM: имя + аргументы."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: "dict[str, Any] | ToolCall") -> "ToolCall":
        if isinstance(data, ToolCall):
            return data
        return cls(name=str(data.get("name", "")), arguments=dict(data.get("arguments") or {}))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments}


@dataclass
class Done:
    """Готовый ответ: результат чтения или уже выполненной записи.

    `actions` — команды интерфейсу (например, открыть карточку клиента): веб-панель их исполняет, Telegram-бот
    игнорирует, ему достаточно текста.
    """

    text: str
    actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Refuse:
    """Отказ: нет прав, не найдено, некорректные данные. Текст — для пользователя."""

    text: str


@dataclass
class Confirm:
    """Пишущее действие готово к выполнению и ждёт «да/нет».

    `args` — уже разрешённые аргументы (id вместо имён): выполняется ровно то, что пользователь подтвердил.
    """

    text: str
    tool: str
    args: dict[str, Any]


@dataclass
class Choose:
    """Найдено несколько подходящих записей — пользователь выбирает одну (кнопки).

    После выбора инструмент запускается заново с `args[param] = id выбранной записи`.
    """

    prompt: str
    tool: str
    param: str
    options: list[tuple[int, str]]
    args: dict[str, Any]


Outcome = Done | Refuse | Confirm | Choose


@dataclass
class Pending:
    """Ожидающее решение пользователя: подтверждение или выбор. `queue` — остальные вызовы того же сообщения."""

    kind: str  # "confirm" | "choose"
    tool: str
    args: dict[str, Any]
    text: str
    param: str = ""
    options: list[tuple[int, str]] = field(default_factory=list)
    queue: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tool": self.tool,
            "args": self.args,
            "text": self.text,
            "param": self.param,
            "options": [[i, n] for i, n in self.options],
            "queue": self.queue,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Pending":
        return cls(
            kind=data["kind"],
            tool=data["tool"],
            args=dict(data.get("args") or {}),
            text=data.get("text", ""),
            param=data.get("param", ""),
            options=[(int(i), str(n)) for i, n in data.get("options") or []],
            queue=list(data.get("queue") or []),
        )
