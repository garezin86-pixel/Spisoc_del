# src/ai/agent.py
"""Агент: превращает фразу пользователя в вызовы инструментов и ведёт диалог подтверждений.

Транспорт-независим: бот, веб-интерфейс и API передают текст (или уже готовые вызовы после распознавания голоса) и
получают `Turn` — сообщения для показа и, если нужно решение пользователя, `Pending`. Pending сериализуется в
обычный dict (`to_dict`), его можно хранить где угодно между сообщениями.

Правила:
- чтение выполняется сразу; запись — только после явного «да» (`confirm`);
- несколько подходящих записей — не угадываем, а просим выбрать (`choose`);
- несколько вызовов в одной фразе идут по очереди: следующий готовится только после того, как решён предыдущий
  (иначе «создай клиента и сделку для него» не нашёл бы только что созданного клиента).
"""

import re
from typing import Protocol

from src.ai.context import AIContext
from src.ai.registry import ToolRegistry
from src.ai.types import Choose, Confirm, Done, Pending, Refuse, ToolCall

MAX_CALLS = 5  # больше вызовов за одну фразу не выполняем: защита от «размножения» команд
_FAILURE_PREFIXES = ("❌", "⛔", "❓")


def strip_markdown(text: str) -> str:
    """Ответ модели без Markdown: в Telegram (HTML) и обычном тексте «**жирный**» выглядит как мусор."""
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text, flags=re.S)
    text = text.replace("`", "")
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"^(\s*)[-*]\s+", r"\1• ", text, flags=re.M)
    return text.strip()


class LLMClient(Protocol):
    """Модель, которая по тексту и истории выбирает инструменты. Реализация (Groq и т.п.) — отдельный модуль."""

    async def plan(self, text: str, history: list[dict], *, tools: list[dict], hints: str) -> list[dict]:
        """Список вызовов [{"name", "arguments"}]; ответ обычным текстом — {"name": "text_response", ...}."""
        ...


class Turn:
    """Итог шага: что показать пользователю и, если нужно, что он должен решить."""

    def __init__(self, messages: list[str], pending: Pending | None = None) -> None:
        self.messages = messages
        self.pending = pending

    def __repr__(self) -> str:  # для отладки и сообщений об ошибках в тестах
        return f"Turn(messages={self.messages!r}, pending={self.pending!r})"


class AIAgent:
    def __init__(self, registry: ToolRegistry, llm: LLMClient | None = None) -> None:
        self.registry = registry
        self.llm = llm

    # ── вход: фраза или готовые вызовы ───────────────────────────────────────
    async def handle_text(self, ctx: AIContext, text: str, history: list[dict]) -> Turn:
        if self.llm is None:
            raise RuntimeError("AIAgent создан без LLM: используйте run_calls с готовыми вызовами")
        calls = await self.llm.plan(
            text, history, tools=self.registry.definitions(ctx.user), hints=self.registry.hints(ctx.user)
        )
        return await self.run_calls(ctx, calls)

    async def run_calls(self, ctx: AIContext, calls: list[dict] | list[ToolCall]) -> Turn:
        queue = [ToolCall.from_dict(c) for c in calls][:MAX_CALLS]
        return await self._drain(ctx, queue, [])

    # ── решения пользователя ─────────────────────────────────────────────────
    async def confirm(self, ctx: AIContext, pending: Pending) -> Turn:
        """«Да»: выполнить подтверждённое действие и продолжить очередь."""
        if pending.kind != "confirm":
            return Turn(["❌ Сейчас нечего подтверждать."])
        text = await self.registry.commit(ctx, pending.tool, pending.args)
        if text.startswith(_FAILURE_PREFIXES):
            return Turn([text])  # сбой записи: зависимые вызовы из очереди не выполняем
        return await self._drain(ctx, [ToolCall.from_dict(c) for c in pending.queue], [text])

    @staticmethod
    def cancel() -> Turn:
        return Turn(["❌ Отменено."])

    async def choose(self, ctx: AIContext, pending: Pending, option_id: int) -> Turn:
        """Пользователь выбрал вариант: запустить инструмент заново с выбранным id и продолжить очередь."""
        if pending.kind != "choose" or option_id not in {i for i, _ in pending.options}:
            return Turn(["❌ Такого варианта нет."], pending)
        call = ToolCall(pending.tool, {**pending.args, pending.param: option_id})
        return await self._drain(ctx, [call, *[ToolCall.from_dict(c) for c in pending.queue]], [])

    # ── внутреннее ───────────────────────────────────────────────────────────
    async def _drain(self, ctx: AIContext, queue: list[ToolCall], messages: list[str]) -> Turn:
        while queue:
            call = queue.pop(0)
            if call.name == "text_response":
                if text := strip_markdown(str(call.arguments.get("text") or "")):
                    messages.append(text)
                continue
            outcome = await self.registry.run(ctx, call)
            rest = [c.to_dict() for c in queue]
            if isinstance(outcome, (Done, Refuse)):
                messages.append(outcome.text)
                if isinstance(outcome, Refuse):
                    break  # отказ: остальные вызовы фразы, скорее всего, от него зависят
            elif isinstance(outcome, Confirm):
                return Turn(messages, Pending("confirm", outcome.tool, outcome.args, outcome.text, queue=rest))
            elif isinstance(outcome, Choose):
                return Turn(
                    messages,
                    Pending("choose", outcome.tool, outcome.args, outcome.prompt, outcome.param, outcome.options, rest),
                )
        return Turn(messages)
