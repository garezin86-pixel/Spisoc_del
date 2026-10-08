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

Межпроцессная шина (Redis pub/sub)
----------------------------------
WebSocket-соединения живут в процессе API, а события порождает не только он:
Telegram-бот работает ОТДЕЛЬНЫМ процессом (src.bot.runner) и тоже рассылает
сообщения чата и принудительно отключает заблокированных. Без общей шины у бота
был бы свой пустой WSManager, и такие события молча терялись бы (то же — при
нескольких воркерах API). Поэтому публичные методы рассылки/отключения, если шина
включена (start_redis_bridge), публикуют сообщение в канал Redis, а каждый API-процесс
доставляет его СВОИМ локальным соединениям. Без шины (тесты, одиночный запуск)
всё работает в процессе, как раньше.
"""

import asyncio
import json
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from fastapi import WebSocket

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

WS_CHANNEL = "ws:events"


class WSManager:
    def __init__(self):
        # user_id → set of WebSocket connections
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        # user_id → workspace_id. Нужен, чтобы broadcast_all не рассылал
        # событие пользователям чужих компаний.
        self._workspace_of: dict[int, int | None] = {}
        # Redis-шина: None — локальный режим (доставка в этом же процессе).
        self._redis: "Redis | None" = None
        self._listener: asyncio.Task | None = None  # есть только в процессе API (listen=True)

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

    # ── Межпроцессная шина ───────────────────────────────────────────────────
    async def start_redis_bridge(self, redis: "Redis", *, listen: bool) -> None:
        """Включает шину. listen=True — процесс API (держит соединения и слушает канал);
        listen=False — процесс без соединений (бот): только публикует.

        Повторный вызов безопасен. Ошибка подписки не мешает запуску: пока шина
        не поднялась, API доставляет события локально (см. _via_bridge).
        """
        await self.stop_redis_bridge()
        self._redis = redis
        if not listen:
            return
        ready = asyncio.Event()
        self._listener = asyncio.create_task(self._listen_loop(ready), name="ws-redis-bridge")
        try:
            await asyncio.wait_for(ready.wait(), timeout=5)
        except asyncio.TimeoutError:
            logger.warning("WS Redis bridge: подписка не подтвердилась за 5 с, продолжаем (будет переподключение)")

    async def stop_redis_bridge(self) -> None:
        task, self._listener = self._listener, None
        self._redis = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _listen_loop(self, ready: asyncio.Event) -> None:
        delay = 1.0
        redis = self._redis
        if redis is None:
            return
        while True:
            pubsub = None
            try:
                pubsub = redis.pubsub()
                await pubsub.subscribe(WS_CHANNEL)
                ready.set()
                delay = 1.0
                async for message in pubsub.listen():
                    if message.get("type") == "message":
                        await self._handle_remote(message.get("data"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — Redis моргнул: переподключаемся, события за паузу потеряны (best effort)
                logger.warning("WS Redis bridge: %s; переподключение через %.0f с", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:  # noqa: BLE001
                        pass

    async def _handle_remote(self, raw) -> None:
        """Доставляет сообщение с шины локальным соединениям. Мусор игнорируется."""
        try:
            msg = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            op = msg["op"]
            if op == "users":
                await self._deliver_to_users([int(u) for u in msg["user_ids"]], msg["event"], msg["data"])
            elif op == "all":
                await self._deliver_to_workspace(msg["workspace_id"], msg["event"], msg["data"])
            elif op == "disconnect_user":
                await self._disconnect_user_local(int(msg["user_id"]), reason=msg["reason"])
            elif op == "disconnect_workspace":
                await self._disconnect_workspace_local(int(msg["workspace_id"]), reason=msg["reason"])
            else:
                logger.warning("WS Redis bridge: неизвестная операция %r", op)
        except Exception as exc:  # noqa: BLE001 — одно кривое сообщение не должно ронять слушателя
            logger.warning("WS Redis bridge: не удалось обработать сообщение: %s", exc)

    async def _via_bridge(self, message: dict) -> bool:
        """True — сообщение передано шине и доставку выполнит слушатель (вызывающему
        делать нечего). False — шины нет или она недоступна, а локальные соединения
        в этом процессе есть: вызывающий доставляет сам."""
        if self._redis is None:
            return False
        try:
            await self._redis.publish(WS_CHANNEL, json.dumps(message, ensure_ascii=False))
            return True
        except Exception as exc:  # noqa: BLE001
            if self._listener is not None:  # процесс API: соединения здесь, доставим локально
                logger.warning("WS Redis bridge: publish не удался (%s), доставка локально", exc)
                return False
            logger.error("WS Redis bridge: publish не удался (%s), событие потеряно", exc)
            return True

    # ── Отключение ───────────────────────────────────────────────────────────
    async def disconnect_user(self, user_id: int, *, reason: str = "Account disabled") -> int:
        """Закрывает все соединения пользователя (заблокировали, пока он online).

        Код 4001 — тот же, что при ошибке авторизации: клиент не должен
        переподключаться с тем же токеном. Работает из любого процесса (бот, админка)
        через шину. Возвращает число закрытых соединений ЭТОГО процесса; при передаче
        через шину фактическое число неизвестно, возвращается 0.
        """
        if await self._via_bridge({"op": "disconnect_user", "user_id": user_id, "reason": reason}):
            return 0
        return await self._disconnect_user_local(user_id, reason=reason)

    async def disconnect_workspace(self, workspace_id: int, *, reason: str = "Company disabled") -> int:
        """Закрывает соединения всех пользователей компании (компанию отключили)."""
        if await self._via_bridge(
            {
                "op": "disconnect_workspace",
                "workspace_id": workspace_id,
                "reason": reason,
            }
        ):
            return 0
        return await self._disconnect_workspace_local(workspace_id, reason=reason)

    async def _disconnect_user_local(self, user_id: int, *, reason: str) -> int:
        sockets = list(self._connections.pop(user_id, set()))
        self._workspace_of.pop(user_id, None)
        for ws in sockets:
            try:
                await ws.close(code=4001, reason=reason)
            except Exception:  # noqa: BLE001 — соединение могло уже закрыться само
                pass
        if sockets:
            logger.info(
                "WS force-disconnected: user_id=%s connections=%s",
                user_id,
                len(sockets),
            )
        return len(sockets)

    async def _disconnect_workspace_local(self, workspace_id: int, *, reason: str) -> int:
        user_ids = [uid for uid, ws_id in list(self._workspace_of.items()) if ws_id == workspace_id]
        closed = 0
        for uid in user_ids:
            closed += await self._disconnect_user_local(uid, reason=reason)
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
        """Рассылает событие списку пользователей (из любого процесса — через шину)."""
        if await self._via_bridge({"op": "users", "user_ids": list(user_ids), "event": event, "data": data}):
            return
        await self._deliver_to_users(user_ids, event, data)

    async def broadcast_all(self, event: str, data: dict, *, workspace_id: int | None) -> None:
        """Рассылает событие всем подключённым пользователям ОДНОГО workspace.

        workspace_id обязателен (keyword-only, без значения по умолчанию) —
        чтобы нельзя было случайно разослать событие всем компаниям сразу.
        Соединения без известного workspace (None) получают событие только
        если workspace_id тоже None (платформенный режим/тесты).
        """
        if await self._via_bridge({"op": "all", "workspace_id": workspace_id, "event": event, "data": data}):
            return
        await self._deliver_to_workspace(workspace_id, event, data)

    async def _deliver_to_users(self, user_ids: list[int], event: str, data: dict) -> None:
        await asyncio.gather(
            *[self.send_to_user(uid, event, data) for uid in user_ids],
            return_exceptions=True,
        )

    async def _deliver_to_workspace(self, workspace_id: int | None, event: str, data: dict) -> None:
        user_ids = [uid for uid in list(self._connections.keys()) if self._workspace_of.get(uid) == workspace_id]
        await self._deliver_to_users(user_ids, event, data)


# Глобальный синглтон
ws_manager = WSManager()
