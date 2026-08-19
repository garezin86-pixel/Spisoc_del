import os

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Окружение. Дефолт "production" — намеренно fail-safe: та же логика уже
    # используется в src/core/sentry.py и src/core/logging.py (os.getenv("ENV",
    # "production")). Если забыл выставить ENV — считаем что это прод и требуем
    # все критичные секреты, а не тихо стартуем на дев-дефолтах.
    env: str = Field(default="production", alias="ENV")

    # JWT
    secret_key: str = Field(default="", alias="SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/spisok_del_db",
        alias="DATABASE_URL",
    )

    # Redis
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: str | None = Field(default=None, alias="REDIS_PASSWORD")

    # SQLAdmin
    admin_secret_key: str = Field(default="", alias="ADMIN_SECRET_KEY")

    # Хранится как обычная строка ("1.2.3.4,5.6.7.8"), а не list[str] —
    # pydantic-settings трактует list-типы как "сложные" и пытается сначала
    # распарсить переменную окружения как JSON, что падает на обычной
    # comma-separated строке ещё до вызова любых validator'ов. Поэтому парсинг
    # в список вынесен в отдельный @property ниже — там уже честный list[str].
    admin_allowed_ips_raw: str = Field(default="", alias="ADMIN_ALLOWED_IPS")

    @property
    def admin_allowed_ips(self) -> list[str]:
        if not self.admin_allowed_ips_raw:
            return []
        return [ip.strip() for ip in self.admin_allowed_ips_raw.split(",") if ip.strip()]

    # Telegram
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    # ID Telegram-группы, привязанной к общему каналу командного чата (см.
    # src/bot/handlers/chat_bridge.py). 0/не задано — мост выключен.
    chat_bridge_group_id: int = Field(default=0, alias="CHAT_BRIDGE_GROUP_ID")

    # AI
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    super_admin_tg_id: int = Field(default=0, alias="SUPER_ADMIN_TG_ID")

    # Monitoring
    grafana_admin_password: str = Field(default="admin", alias="GRAFANA_ADMIN_PASSWORD")

    refresh_secret_key: str = Field(default="", alias="REFRESH_SECRET_KEY")
    refresh_token_expire_days: int = Field(default=30, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    # Cloudflare R2 (S3-совместимое хранилище для вложений) — на будущее
    r2_account_id: str = Field(default="", alias="R2_ACCOUNT_ID")
    r2_access_key_id: str = Field(default="", alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = Field(default="", alias="R2_SECRET_ACCESS_KEY")
    r2_bucket_name: str = Field(default="spisok-del-attachments", alias="R2_BUCKET_NAME")
    r2_public_base_url: str = Field(default="", alias="R2_PUBLIC_BASE_URL")

    # Локальное хранилище вложений (используется пока R2 не подключён).
    # ВНИМАНИЕ: на Render free tier диск ephemeral — файлы пропадают
    # при рестарте/редеплое. Подходит для разработки и для платных планов
    # с persistent disk, не подходит для прод на free tier надолго.
    attachments_storage_path: str = Field(default="storage/attachments", alias="ATTACHMENTS_STORAGE_PATH")

    # Web Push (VAPID) — генерируется ОДИН РАЗ через scripts/generate_vapid_keys.py
    # и сохраняется в .env. Перегенерация ключей аннулирует ВСЕ существующие
    # подписки браузеров пользователей — они будут вынуждены заново включить
    # push-уведомления после смены ключей.
    vapid_private_key: str = Field(default="", alias="VAPID_PRIVATE_KEY")
    vapid_public_key: str = Field(default="", alias="VAPID_PUBLIC_KEY")
    vapid_claims_email: str = Field(default="admin@example.com", alias="VAPID_CLAIMS_EMAIL")

    @model_validator(mode="after")
    def _require_real_secrets_in_production(self) -> "Settings":
        """Не даёт приложению тихо стартовать в проде с пустыми секретами.

        Раньше SECRET_KEY/ADMIN_SECRET_KEY/REFRESH_SECRET_KEY дефолтились в "" —
        если забыть создать .env.prod (а в docker-compose.prod.yml он помечен
        required: false), контейнер стартовал "успешно", просто подписывая JWT
        пустой строкой. Это тихая дыра в безопасности, а не громкая ошибка.
        В тестах ENV=test — проверка не применяется.
        """
        if self.env.lower() in ("prod", "production"):
            missing = [
                name
                for name, value in (
                    ("SECRET_KEY", self.secret_key),
                    ("ADMIN_SECRET_KEY", self.admin_secret_key),
                    ("REFRESH_SECRET_KEY", self.refresh_secret_key),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "ENV=production, но не заданы обязательные секреты: "
                    f"{', '.join(missing)}. Создай .env.prod (см. .env.prod.example) "
                    "или задай их через переменные окружения перед запуском."
                )
        return self


settings = Settings()

# Совместимость со старым кодом — убирай постепенно
ENV = settings.env
SECRET_KEY = settings.secret_key
ALGORITHM = settings.algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
DATABASE_URL = settings.database_url
REDIS_HOST = settings.redis_host
REDIS_PORT = settings.redis_port
REDIS_DB = settings.redis_db
REDIS_PASSWORD = settings.redis_password
ADMIN_SECRET_KEY = settings.admin_secret_key
ADMIN_ALLOWED_IPS = settings.admin_allowed_ips
BOT_TOKEN = settings.bot_token
CHAT_BRIDGE_GROUP_ID = settings.chat_bridge_group_id
GROQ_API_KEY = settings.groq_api_key
GEMINI_API_KEY = settings.gemini_api_key
SUPER_ADMIN_TG_ID = settings.super_admin_tg_id

FRONTEND_URL = os.getenv("FRONTEND_URL", "")

REFRESH_SECRET_KEY = settings.refresh_secret_key
REFRESH_TOKEN_EXPIRE_DAYS = settings.refresh_token_expire_days

R2_ACCOUNT_ID = settings.r2_account_id
R2_ACCESS_KEY_ID = settings.r2_access_key_id
R2_SECRET_ACCESS_KEY = settings.r2_secret_access_key
R2_BUCKET_NAME = settings.r2_bucket_name

VAPID_PRIVATE_KEY = settings.vapid_private_key
VAPID_PUBLIC_KEY = settings.vapid_public_key
VAPID_CLAIMS_EMAIL = settings.vapid_claims_email
R2_PUBLIC_BASE_URL = settings.r2_public_base_url.rstrip("/")

ATTACHMENTS_STORAGE_PATH = settings.attachments_storage_path
