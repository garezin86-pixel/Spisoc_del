# src/ai/registry.py
"""Реестр AI-инструментов: описание для LLM, права, выполнение.

Инструмент — это:
- `definition` для LLM (формат function calling);
- `allowed(user)` — роль-гейт: недоступный инструмент не показывается LLM и не выполняется, даже если LLM его
  «придумала» (права проверяются здесь, а не только в промпте);
- `run` — разбор аргументов и подготовка: чтение выполняется сразу (Done), запись возвращает Confirm с
  разрешёнными id и ждёт «да»;
- `commit` — само пишущее действие, вызывается только после подтверждения пользователя.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import HTTPException
from pydantic import ValidationError

from src.ai.context import AIContext
from src.ai.permissions import always
from src.ai.types import Outcome, Refuse, ToolCall

logger = structlog.get_logger()

RunFn = Callable[[AIContext, dict[str, Any]], Awaitable[Outcome]]
CommitFn = Callable[[AIContext, dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: RunFn
    commit: CommitFn | None = None  # есть у пишущих инструментов
    allowed: Callable[[Any], bool] = always
    hint: str = ""  # строка для системного промпта: когда вызывать

    @property
    def writes(self) -> bool:
        return self.commit is not None

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


def _validation_text(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", ()))
    return f"❌ Некорректные данные{f' ({where})' if where else ''}: {first.get('msg', 'проверьте значения')}"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Инструмент {tool.name} уже зарегистрирован")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def available(self, user: Any) -> list[Tool]:
        return [t for t in self._tools.values() if t.allowed(user)]

    def definitions(self, user: Any) -> list[dict[str, Any]]:
        """Описания инструментов, доступных пользователю, — то, что получает LLM."""
        return [t.definition() for t in self.available(user)]

    def hints(self, user: Any) -> str:
        return "\n".join(t.hint for t in self.available(user) if t.hint)

    async def run(self, ctx: AIContext, call: ToolCall) -> Outcome:
        """Подготовить вызов: проверить права, разобрать аргументы, выполнить чтение или собрать подтверждение."""
        tool = self._tools.get(call.name)
        if tool is None:
            return Refuse(f"❓ Неизвестная команда: {call.name}")
        if not tool.allowed(ctx.user):
            await logger.awarning("ai_tool_denied", tool=call.name, user_id=getattr(ctx.user, "id", None))
            return Refuse("⛔ У вас нет прав на это действие.")
        try:
            return await tool.run(ctx, dict(call.arguments))
        except HTTPException as exc:
            return Refuse(f"❌ {exc.detail}")
        except ValidationError as exc:
            return Refuse(_validation_text(exc))

    async def commit(self, ctx: AIContext, tool_name: str, args: dict[str, Any]) -> str:
        """Выполнить подтверждённую запись. Права проверяются повторно: между вопросом и «да» они могли измениться."""
        tool = self._tools.get(tool_name)
        if tool is None or tool.commit is None:
            return f"❓ Неизвестная команда: {tool_name}"
        if not tool.allowed(ctx.user):
            await logger.awarning("ai_tool_denied", tool=tool_name, user_id=getattr(ctx.user, "id", None))
            return "⛔ У вас нет прав на это действие."
        try:
            text = await tool.commit(ctx, dict(args))
        except HTTPException as exc:
            return f"❌ {exc.detail}"
        except ValidationError as exc:
            return _validation_text(exc)
        await logger.ainfo("ai_tool_committed", tool=tool_name, user_id=ctx.user.id)
        return text


def default_registry() -> ToolRegistry:
    """Реестр со всеми инструментами CRM и задач. Один экземпляр на процесс (инструменты без состояния)."""
    global _default
    if _default is None:
        from src.ai.tools import register_all

        registry = ToolRegistry()
        register_all(registry)
        _default = registry
    return _default


_default: ToolRegistry | None = None
