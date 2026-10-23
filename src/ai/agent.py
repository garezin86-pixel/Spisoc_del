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


_PRIORITY_WORDS = (
    (r"срочн|критич|горит", "critical"),
    (r"важн|высок", "high"),
    (r"низк|неважн|не\s+срочн", "low"),
    (r"обычн|средн|нормальн", "medium"),
)
_PRIORITY_PHRASE = re.compile(
    r"^\s*(?:сделай|сделать|поставь|измени|смени)\s+задач\w*\s+(?P<task>.+?)[,\s]+(?:как\s+|на\s+)?"
    r"(?P<word>срочн|критич|важн|высок|низк|неважн|обычн|средн|нормальн)\w*[\s.!]*$",
    re.IGNORECASE | re.DOTALL,
)


def fix_priority_intent(text: str, calls: list[dict]) -> list[dict]:
    """«Сделай задачу X срочной» — это смена приоритета, а не создание задачи.

    Модель иногда понимает такую фразу как create_task. Это не мелочь: после «да» появилась бы лишняя задача, а
    нужная осталась бы прежней. Подсказки в промпте этого не гарантируют, поэтому жёсткий случай разбираем по тексту:
    фраза должна начинаться с «сделай/поставь/измени/смени задачу ...» и заканчиваться названием приоритета.
    Если модель вернула create_task, а не смену приоритета — подменяем вызов.
    """
    if not any(c.get("name") == "create_task" for c in calls):
        return calls
    m = _PRIORITY_PHRASE.match(text)
    if m is None:
        return calls
    word = m.group("word").lower()
    priority = next((p for pattern, p in _PRIORITY_WORDS if re.match(pattern, word)), None)
    task = m.group("task").strip(' ,.«»"')
    if priority is None or not task:
        return calls
    return [{"name": "update_task_priority", "arguments": {"search": task, "priority": priority}}]


_PRIORITY_MENTION = re.compile(r"срочн|критич|горит|важн|высок|низк|приоритет|asap", re.IGNORECASE)


def drop_unasked_priority(text: str, calls: list[dict]) -> list[dict]:
    """Приоритет новой задачи — только если он назван в текущей фразе.

    Модель видит историю диалога и может перенести «срочно» из прошлой команды в новую задачу. Такая задача
    создавалась бы с чужим приоритетом, поэтому без слов о приоритете в самой фразе поле убираем (останется «Средний»).
    """
    if _PRIORITY_MENTION.search(text):
        return calls
    fixed: list[dict] = []
    for c in calls:
        args = c.get("arguments") or {}
        if c.get("name") == "create_task" and args.get("priority") not in (None, "medium"):
            c = {**c, "arguments": {k: v for k, v in args.items() if k != "priority"}}
        fixed.append(c)
    return fixed


class LLMClient(Protocol):
    """Модель, которая по тексту и истории выбирает инструменты. Реализация (Groq и т.п.) — отдельный модуль."""

    async def plan(self, text: str, history: list[dict], *, tools: list[dict], hints: str) -> list[dict]:
        """Список вызовов [{"name", "arguments"}]; ответ обычным текстом — {"name": "text_response", ...}."""
        ...


class Turn:
    """Итог шага: что показать пользователю и, если нужно, что он должен решить."""

    def __init__(self, messages: list[str], pending: Pending | None = None, actions: list[dict] | None = None) -> None:
        self.messages = messages
        self.pending = pending
        self.actions = actions or []  # команды интерфейсу: [{"type": "open_client", "client_id": 5}]

    def __repr__(self) -> str:  # для отладки и сообщений об ошибках в тестах
        return f"Turn(messages={self.messages!r}, pending={self.pending!r}, actions={self.actions!r})"


class AIAgent:
    def __init__(self, registry: ToolRegistry, llm: LLMClient | None = None) -> None:
        self.registry = registry
        self.llm = llm

    # ── вход: фраза или готовые вызовы ───────────────────────────────────────
    async def handle_text(self, ctx: AIContext, text: str, history: list[dict]) -> Turn:
        if self.llm is None:
            raise RuntimeError("AIAgent создан без LLM: используйте run_calls с готовыми вызовами")
        calls = await self.llm.plan(
            text,
            history,
            tools=self.registry.definitions(ctx.user),
            hints=self.registry.hints(ctx.user) + ctx.focus_hint(),
        )
        return await self.run_calls(ctx, drop_unasked_priority(text, fix_priority_intent(text, calls)))

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
        actions: list[dict] = []
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
                if isinstance(outcome, Done):
                    actions.extend(outcome.actions)
                if isinstance(outcome, Refuse):
                    break  # отказ: остальные вызовы фразы, скорее всего, от него зависят
            elif isinstance(outcome, Confirm):
                return Turn(messages, Pending("confirm", outcome.tool, outcome.args, outcome.text, queue=rest), actions)
            elif isinstance(outcome, Choose):
                return Turn(
                    messages,
                    Pending("choose", outcome.tool, outcome.args, outcome.prompt, outcome.param, outcome.options, rest),
                    actions,
                )
        return Turn(messages, None, actions)
