# tests/test_ws_router.py
"""
Тесты для src/routers/ws_router.py — WebSocket-эндпоинт /api/ws.

Используем реальный FastAPI TestClient.websocket_connect (ASGI-протокол
эмулируется полностью, без сети). decode_access_token и UnitOfWork мокаются
на уровне модуля ws_router — сам эндпоинт не через Depends их берёт,
а импортирует напрямую.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.core.ws_manager import ws_manager
from src.routers.ws_router import router as ws_router


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(ws_router, prefix="/api")
    return test_app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def make_fake_uow(user=None):
    """Возвращает объект, который ведёт себя как `async with UnitOfWork(...) as uow`."""
    uow = MagicMock()
    uow.users.get_by_id = AsyncMock(return_value=user)

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield uow

    return _cm


@pytest.fixture
def mock_auth_ok():
    """decode_access_token успешно возвращает payload для user_id=1."""
    with patch("src.routers.ws_router.decode_access_token") as mock_decode:
        mock_decode.return_value = {"sub": "1"}
        yield mock_decode


@pytest.fixture
def mock_uow_user_exists():
    fake_user = MagicMock(id=1)
    with (
        patch("src.routers.ws_router.UnitOfWork", side_effect=make_fake_uow(fake_user)),
        patch("src.routers.ws_router.get_session_maker", return_value=MagicMock()),
    ):
        yield fake_user


@pytest.fixture
def mock_uow_user_missing():
    with (
        patch("src.routers.ws_router.UnitOfWork", side_effect=make_fake_uow(None)),
        patch("src.routers.ws_router.get_session_maker", return_value=MagicMock()),
    ):
        yield


@pytest.fixture(autouse=True)
def reset_ws_manager():
    """Чистим глобальный singleton ws_manager между тестами, чтобы они не влияли друг на друга."""
    yield
    ws_manager._connections.clear()


class TestAuthentication:
    def test_invalid_token_closes_with_4001(self, client):
        with patch("src.routers.ws_router.decode_access_token", side_effect=Exception("bad token")):
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/api/ws?token=garbage"):
                    pass

            assert exc_info.value.code == 4001

    def test_missing_token_query_param_rejected(self, client):
        # token обязателен (Query(...)) — без него FastAPI отклонит handshake до входа в функцию
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws"):
                pass

    def test_nonexistent_user_closes_with_4001(self, client, mock_auth_ok, mock_uow_user_missing):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/ws?token=valid-token"):
                pass

        assert exc_info.value.code == 4001

    def test_valid_token_and_existing_user_connects(self, client, mock_auth_ok, mock_uow_user_exists):
        with client.websocket_connect("/api/ws?token=valid-token") as ws:
            message = ws.receive_json()

        assert message["event"] == "connected"
        assert message["data"]["user_id"] == 1


class TestConnectionLifecycle:
    def test_sends_welcome_message_with_user_id(self, client, mock_auth_ok, mock_uow_user_exists):
        with client.websocket_connect("/api/ws?token=valid-token") as ws:
            message = ws.receive_json()

        assert message == {"event": "connected", "data": {"user_id": 1, "message": "WebSocket connected"}}

    def test_registers_connection_in_ws_manager(self, client, mock_auth_ok, mock_uow_user_exists):
        assert ws_manager.total_connections == 0

        with client.websocket_connect("/api/ws?token=valid-token") as ws:
            ws.receive_json()  # welcome message
            assert ws_manager.total_connections == 1

    def test_disconnects_from_ws_manager_on_close(self, client, mock_auth_ok, mock_uow_user_exists):
        with client.websocket_connect("/api/ws?token=valid-token") as ws:
            ws.receive_json()

        # Соединение закрыто — менеджер должен почистить запись
        assert ws_manager.total_connections == 0

    def test_ping_receives_pong(self, client, mock_auth_ok, mock_uow_user_exists):
        with client.websocket_connect("/api/ws?token=valid-token") as ws:
            ws.receive_json()  # welcome
            ws.send_text("ping")
            response = ws.receive_text()

        assert response == '{"event":"pong","data":{}}'

    def test_non_ping_text_is_ignored_without_crashing(self, client, mock_auth_ok, mock_uow_user_exists):
        with client.websocket_connect("/api/ws?token=valid-token") as ws:
            ws.receive_json()  # welcome
            ws.send_text("какой-то произвольный текст")
            # Соединение не должно падать — проверяем, что после этого ping всё ещё работает
            ws.send_text("ping")
            response = ws.receive_text()

        assert response == '{"event":"pong","data":{}}'

    def test_can_broadcast_event_to_connected_user(self, client, mock_auth_ok, mock_uow_user_exists):
        with client.websocket_connect("/api/ws?token=valid-token") as ws:
            ws.receive_json()  # welcome

            client.portal.call(ws_manager.send_to_user, 1, "task_created", {"id": 42})

            message = ws.receive_json()

        assert message == {"event": "task_created", "data": {"id": 42}}

    def test_multiple_connections_for_same_user_both_receive_broadcast(
        self, client, mock_auth_ok, mock_uow_user_exists
    ):
        with client.websocket_connect("/api/ws?token=valid-token") as ws1:
            ws1.receive_json()
            with client.websocket_connect("/api/ws?token=valid-token") as ws2:
                ws2.receive_json()

                assert ws_manager.total_connections == 2

                client.portal.call(ws_manager.send_to_user, 1, "ping", {})

                msg1 = ws1.receive_json()
                msg2 = ws2.receive_json()

        assert msg1 == {"event": "ping", "data": {}}
        assert msg2 == {"event": "ping", "data": {}}

    def test_decodes_user_id_from_token_sub_claim(self, client, mock_uow_user_exists):
        with patch("src.routers.ws_router.decode_access_token") as mock_decode:
            mock_decode.return_value = {"sub": "1", "role": "admin", "username": "test"}
            with client.websocket_connect("/api/ws?token=valid-token") as ws:
                message = ws.receive_json()

        assert message["data"]["user_id"] == 1

    def test_unexpected_receive_error_closes_connection_gracefully(self, client, mock_auth_ok, mock_uow_user_exists):
        """
        Если websocket.receive_text() падает с чем-то, кроме WebSocketDisconnect
        (например, обрыв сети на уровне ASGI-сервера), цикл должен корректно
        завершиться через `except Exception: break`, а не уронить весь обработчик —
        ws_manager.disconnect() всё равно обязан отработать в finally.
        """
        from starlette.websockets import WebSocket

        call_count = {"n": 0}
        original_receive_text = WebSocket.receive_text

        async def flaky_receive_text(self):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("connection reset by peer")
            return await original_receive_text(self)

        with patch.object(WebSocket, "receive_text", flaky_receive_text):
            with client.websocket_connect("/api/ws?token=valid-token") as ws:
                ws.receive_json()  # welcome message
                # Сервер сам оборвёт соединение после ошибки в receive_text —
                # клиентская сторона получит закрытие без явного кода (штатный break).

        assert ws_manager.total_connections == 0
