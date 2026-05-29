# Добавить в src/core/config.py:

import os

# Список IP через запятую в .env:
# ADMIN_ALLOWED_IPS=127.0.0.1,192.168.1.100
_raw = os.getenv("ADMIN_ALLOWED_IPS", "")
ADMIN_ALLOWED_IPS: list[str] = [ip.strip() for ip in _raw.split(",") if ip.strip()]


# Добавить в .env:
# ADMIN_ALLOWED_IPS=127.0.0.1,192.168.1.100
#
# Если переменная не задана или пустая — IP-фильтр отключён (пускает всех).
# Это удобно для локальной разработки.
