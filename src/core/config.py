import os

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # JWT
    secret_key: str = Field(default="", alias="SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )

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
    # admin_allowed_ips: list[str] = Field(
    #     default_factory=list, alias="ADMIN_ALLOWED_IPS"
    # )
    # Замени поле и валидатор на это:
    admin_allowed_ips: str = Field(default="", alias="ADMIN_ALLOWED_IPS")

    @field_validator("admin_allowed_ips", mode="after")
    @classmethod
    def parse_allowed_ips(cls, v: str) -> list[str]:  # type: ignore[override]
        if not v:
            return []
        return [ip.strip() for ip in v.split(",") if ip.strip()]

    # Telegram
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    super_admin_tg_id: int = Field(default=0, alias="SUPER_ADMIN_TG_ID")

    # Monitoring
    grafana_admin_password: str = Field(default="admin", alias="GRAFANA_ADMIN_PASSWORD")


settings = Settings()

# Совместимость со старым кодом — убирай постепенно
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
SUPER_ADMIN_TG_ID = settings.super_admin_tg_id

FRONTEND_URL = os.getenv("FRONTEND_URL", "")
