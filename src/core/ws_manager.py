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

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        await websocket.accept()
        self._connections[user_id].add(websocket)
        logger.info("WS connected: user_id=%s total=%s", user_id, self.total_connections)

    def disconnect(self, websocket: WebSocket, user_id: int) -> None:
        self._connections[user_id].discard(websocket)
        if not self._connections[user_id]:
            del self._connections[user_id]
        logger.info("WS disconnected: user_id=%s total=%s", user_id, self.total_connections)

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

    async def broadcast_all(self, event: str, data: dict) -> None:
        """Рассылает событие всем подключённым пользователям."""
        user_ids = list(self._connections.keys())
        await self.broadcast_to_users(user_ids, event, data)


# Глобальный синглтон
ws_manager = WSManager()
