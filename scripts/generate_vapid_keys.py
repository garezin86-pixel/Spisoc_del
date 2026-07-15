"""
scripts/generate_vapid_keys.py

Генерирует пару VAPID-ключей для веб-push уведомлений. Запускать ОДИН РАЗ
(при первой настройке push) и сохранить вывод в .env — перегенерация
аннулирует все существующие подписки браузеров пользователей.

Использование:
    python scripts/generate_vapid_keys.py
"""

import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid


def main() -> None:
    vapid = Vapid()
    vapid.generate_keys()

    private_pem = vapid.private_pem().decode()

    raw_public_bytes = vapid.public_key.public_bytes(
        encoding=Encoding.X962,
        format=PublicFormat.UncompressedPoint,
    )
    public_b64url = base64.urlsafe_b64encode(raw_public_bytes).rstrip(b"=").decode()

    print("Добавьте это в .env (и .env.prod):\n")
    print(f'VAPID_PRIVATE_KEY="{private_pem}"')
    print(f"VAPID_PUBLIC_KEY={public_b64url}")
    print('VAPID_CLAIMS_EMAIL="mailto:you@example.com"  # замените на реальный email')
    print(
        "\nПерезапустите бэкенд после добавления переменных. Фронтенду ничего "
        "дополнительно настраивать не нужно — он получает VAPID_PUBLIC_KEY "
        "динамически через GET /api/push/vapid-public-key при включении "
        "push-уведомлений (см. PushNotificationsCard в App.jsx)."
    )


if __name__ == "__main__":
    main()
