"""
src/routers/ws_router.py

WebSocket endpoint: /api/ws?token=<JWT>

Клиент подключается с токеном в query string (WebSocket не поддерживает заголовки).
После подключения сервер рассылает события через ws_manager.
"""

import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.core.dependencies import decode_access_token
from src.core.ws_manager import ws_manager
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    """
    WebSocket соединение для realtime обновлений.

    Подключение: ws://host/api/ws?token=<JWT>

    Получаемые события (JSON):
    {"event": "task_created", "data": {...}}
    {"event": "task_updated", "data": {"id": 1, "field": "status", "value": "done"}}
    {"event": "task_deleted", "data": {"id": 1}}
    {"event": "task_restored", "data": {"id": 1}}
    {"event": "comment_added", "data": {"task_id": 1, "comment": {...}}}
    {"event": "kanban_moved", "data": {"id": 1, "status": "done"}}
    {"event": "ping", "data": {}}  — keepalive каждые 30 сек
    """
    # Аутентификация по JWT
    try:
        payload = decode_access_token(token)
        user_id: int = int(payload["sub"])
    except Exception as e:
        logger.warning("WS auth failed: %s", e)
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Проверяем что пользователь существует
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_id(user_id)
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return

    await ws_manager.connect(websocket, user_id)

    try:
        # Отправляем приветственное сообщение
        import json

        await websocket.send_text(
            json.dumps(
                {
                    "event": "connected",
                    "data": {"user_id": user_id, "message": "WebSocket connected"},
                }
            )
        )

        # Слушаем входящие сообщения (ping/pong)
        while True:
            try:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text('{"event":"pong","data":{}}')
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.warning("WS receive error: %s", e)
                break

    finally:
        ws_manager.disconnect(websocket, user_id)
