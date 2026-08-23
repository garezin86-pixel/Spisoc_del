# src/core/ssrf_guard.py
"""
Защита от SSRF (Server-Side Request Forgery) для исходящих HTTP-запросов,
URL которых задаёт пользователь, а выполняет их сервер — сейчас это только
вебхуки (src/services/webhook_dispatcher.py), но модуль написан так, чтобы
им можно было закрыть и любой будущий "сходи по ссылке от юзера" функционал.

Атака: пользователь регистрирует вебхук на http://169.254.169.254/... (cloud
metadata endpoint — кража креденшлов облака) или на http://localhost:9090,
http://postgres:5432 и т.п. (сканирование/доступ к внутренней docker-сети).
Сервер сам делает запрос с правами приложения — обычный allowlist по домену
тут не спасает, проверять нужно РЕЗОЛВНУТЫЙ IP, а не строку URL.

Проверка выполняется дважды:
  1. При создании/изменении вебхука (WebhookCreate/WebhookUpdate) — синхронно,
     чтобы явно вернуть 422 с понятной причиной.
  2. Непосредственно перед каждой отправкой в webhook_dispatcher — асинхронно,
     потому что между "создали вебхук" и "событие произошло и полетел запрос"
     могут пройти недели, а DNS-запись могла быть переписана так, чтобы в
     момент проверки резолвиться в публичный IP, а к моменту доставки — в
     приватный (DNS rebinding). Проверка №1 без №2 обходится тривиально.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}


def _is_blocked_ip(ip_str: str) -> bool:
    """True, если по этому IP нельзя стучаться — приватные сети, loopback,
    link-local (сюда попадает и 169.254.169.254 — метадата облаков),
    multicast, reserved, unspecified (0.0.0.0)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # не распарсили IP — считаем небезопасным, а не пропускаем
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def _split_and_check_scheme_and_host(url: str) -> tuple[str, int | None]:
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise ValueError("URL должен начинаться с http:// или https://")
    if not parts.hostname:
        raise ValueError("URL должен содержать хост")
    return parts.hostname, parts.port


def validate_webhook_url_sync(url: str) -> None:
    """Синхронная проверка для pydantic-валидатора (create/update вебхука).
    Резолвит хост через блокирующий socket.getaddrinfo — это разовое
    действие пользователя (не hot path), так что блокировка event loop на
    время DNS-запроса не критична."""
    hostname, _ = _split_and_check_scheme_and_host(url)
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Не удалось резолвить хост '{hostname}': {exc}") from exc
    for family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            raise ValueError(
                f"URL резолвится в адрес из приватного/внутреннего диапазона "
                f"({ip_str}) — такие адреса запрещены для вебхуков"
            )


async def assert_webhook_url_safe(url: str) -> None:
    """Асинхронная повторная проверка перед КАЖДОЙ реальной отправкой —
    см. docstring модуля про DNS rebinding. Бросает ValueError, если URL
    небезопасен; вызывающий код (webhook_dispatcher) должен это ловить и
    не делать запрос."""
    hostname, _ = _split_and_check_scheme_and_host(url)
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Не удалось резолвить хост '{hostname}': {exc}") from exc
    for family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            raise ValueError(
                f"URL резолвится в адрес из приватного/внутреннего диапазона ({ip_str}) — отправка заблокирована"
            )
