"""AI-инструменты CRM и агент, который их вызывает (Этап 5).

Пакет не зависит от aiogram: Telegram-бот, веб-интерфейс и API подключаются к одному реестру через
`default_registry()` и `AIAgent`. Инструменты вызывают сервисы CRM (ClientService, DealService, ...), а не логику
Telegram; права проверяются в самих инструментах (и ещё раз в сервисах), а не только в промпте.
"""

from src.ai.agent import AIAgent, Turn
from src.ai.context import AIContext
from src.ai.registry import ToolRegistry, default_registry
from src.ai.types import Choose, Confirm, Done, Pending, Refuse, ToolCall

__all__ = [
    "AIAgent",
    "AIContext",
    "Choose",
    "Confirm",
    "Done",
    "Pending",
    "Refuse",
    "ToolCall",
    "ToolRegistry",
    "Turn",
    "default_registry",
]
