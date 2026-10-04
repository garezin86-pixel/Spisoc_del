"""
src/core/ws_manager.py

Менеджер WebSocket соединений.
Каждый пользователь может иметь несколько соединений (разные вкладки).

События которые рассылаются:
- task_created   — создана новая задача
- task_updated   — задача обновлена
- task_deleted   — задача удалена (soft delete)
- task_restored  — задача восстановлена
- comment_added  — добавлен комментарий
- kanban_moved   — задача перемещена на канбане
"""

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    def __init__(self):
        # user_id → set of WebSocket connections
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        # user_id → workspace_id. Нужен, чтобы broadcast_all не рассылал
        # событие пользователям чужих компаний.
        self._workspace_of: dict[int, int | None] = {}

    async def connect(self, websocket: WebSocket, user_id: int, workspace_id: int | None = None) -> None:
        await websocket.accept()
        self._connections[user_id].add(websocket)
        self._workspace_of[user_id] = workspace_id
        logger.info("WS connected: user_id=%s total=%s", user_id, self.total_connections)

    def disconnect(self, websocket: WebSocket, user_id: int) -> None:
        self._connections[user_id].discard(websocket)
        if not self._connections[user_id]:
            del self._connections[user_id]
            self._workspace_of.pop(user_id, None)
        logger.info("WS disconnected: user_id=%s total=%s", user_id, self.total_connections)

    async def disconnect_user(self, user_id: int, *, reason: str = "Account disabled") -> int:
        """Закрывает все соединения пользователя (заблокировали, пока он online).

        Код 4001 — тот же, что при ошибке авторизации: клиент не должен
        переподключаться с тем же токеном. Возвращает число закрытых соединений.
        Работает только в этом процессе: при нескольких воркерах нужен общий
        канал (например, Redis pub/sub) — сейчас сервис запускается одним.
        """
        sockets = list(self._connections.pop(user_id, set()))
        self._workspace_of.pop(user_id, None)
        for ws in sockets:
            try:
                await ws.close(code=4001, reason=reason)
            except Exception:  # noqa: BLE001 — соединение могло уже закрыться само
                pass
        if sockets:
            logger.info("WS force-disconnected: user_id=%s connections=%s", user_id, len(sockets))
        return len(sockets)

    async def disconnect_workspace(self, workspace_id: int, *, reason: str = "Company disabled") -> int:
        """Закрывает соединения всех пользователей компании (компанию отключили)."""
        user_ids = [uid for uid, ws_id in list(self._workspace_of.items()) if ws_id == workspace_id]
        closed = 0
        for uid in user_ids:
            closed += await self.disconnect_user(uid, reason=reason)
        return closed

    @property
    def total_connections(self) -> int:
        return sum(len(s) for s in self._connections.values())

    async def send_to_user(self, user_id: int, event: str, data: dict) -> None:
        """Отправляет событие конкретному пользователю во все его вкладки."""
        payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
        dead = set()
        for ws in list(self._connections.get(user_id, set())):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections[user_id].discard(ws)

    async def broadcast_to_users(self, user_ids: list[int], event: str, data: dict) -> None:
        """Рассылает событие списку пользователей."""
        await asyncio.gather(
            *[self.send_to_user(uid, event, data) for uid in user_ids],
            return_exceptions=True,
        )

    async def broadcast_all(self, event: str, data: dict, *, workspace_id: int | None) -> None:
        """Рассылает событие всем подключённым пользователям ОДНОГО workspace.

        workspace_id обязателен (keyword-only, без значения по умолчанию) —
        чтобы нельзя было случайно разослать событие всем компаниям сразу.
        Соединения без известного workspace (None) получают событие только
        если workspace_id тоже None (платформенный режим/тесты).
        """
        user_ids = [uid for uid in list(self._connections.keys()) if self._workspace_of.get(uid) == workspace_id]
        await self.broadcast_to_users(user_ids, event, data)


# Глобальный синглтон
ws_manager = WSManager()
