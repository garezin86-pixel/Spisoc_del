# src/ai/runtime.py
"""Общий для бота и веба агент: реестр инструментов + LLM (Groq). Один экземпляр на процесс."""

from src.ai.agent import AIAgent
from src.ai.llm import GroqLLM
from src.ai.registry import default_registry

_agent: AIAgent | None = None


def get_agent() -> AIAgent:
    global _agent
    if _agent is None:
        _agent = AIAgent(default_registry(), GroqLLM())
    return _agent
