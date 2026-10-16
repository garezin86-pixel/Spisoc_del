# src/ai/permissions.py
"""Права AI-инструментов. Те же правила, что в сервисах CRM (ClientService, DealService, InteractionService).

Зачем дублировать: инструмент должен отказать ДО вопроса «Создать сделку? да/нет», а не после «да». Последним
рубежом остаются сами сервисы: если правила разойдутся, пользователь получит их отказ (403), а не обход прав.
Тест tests/test_ai_permissions.py сверяет решения инструментов с поведением API.
"""

from typing import Any

from src.models.user import UserRole


def is_manager(user: Any) -> bool:
    """admin или manager. getattr — чтобы объект без роли (заглушка, неполный профиль) считался обычным."""
    return getattr(user, "role", None) in (UserRole.admin, UserRole.manager)


def can_create_clients(user: Any) -> bool:
    return is_manager(user)


def can_edit_client(client: Any, user: Any) -> bool:
    """Сделки и взаимодействия клиента: admin, manager и ответственный за клиента."""
    return is_manager(user) or client.owner_id == user.id


def can_manage_deal(deal: Any, user: Any) -> bool:
    """Перевод и правка сделки: admin, manager и ответственный за сделку."""
    return is_manager(user) or deal.owner_id == user.id


def always(user: Any) -> bool:
    return True
