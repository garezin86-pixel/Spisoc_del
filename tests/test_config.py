import pytest

from src.core import config


def test_config_values_are_valid():
    assert isinstance(config.ACCESS_TOKEN_EXPIRE_MINUTES, int)
    assert config.ACCESS_TOKEN_EXPIRE_MINUTES > 0
    assert isinstance(config.DATABASE_URL, str)
    assert config.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert isinstance(config.SECRET_KEY, str)
    assert config.SECRET_KEY != ""


class TestProductionRequiresSecrets:
    """Регресс: SECRET_KEY/ADMIN_SECRET_KEY/REFRESH_SECRET_KEY дефолтились в
    "" и ничто не мешало приложению стартовать в проде с пустыми секретами
    (JWT, подписанный пустой строкой, — тривиально подделываемый). Плюс
    docker-compose.prod.yml раньше держал .env.prod как required: false —
    забытый файл означал тихий откат на дев-дефолты."""

    def test_production_without_secrets_raises(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            config.Settings(_env_file=None, ENV="production", SECRET_KEY="", ADMIN_SECRET_KEY="", REFRESH_SECRET_KEY="")

    def test_production_with_partial_secrets_raises(self):
        """Даже один незаданный секрет из трёх должен блокировать старт."""
        with pytest.raises(Exception):
            config.Settings(
                _env_file=None,
                ENV="production",
                SECRET_KEY="real-secret",
                ADMIN_SECRET_KEY="",
                REFRESH_SECRET_KEY="real-refresh",
            )

    def test_production_with_all_secrets_succeeds(self):
        s = config.Settings(
            _env_file=None,
            ENV="production",
            SECRET_KEY="real-secret",
            ADMIN_SECRET_KEY="real-admin",
            REFRESH_SECRET_KEY="real-refresh",
            DATABASE_URL="postgresql+asyncpg://user:pass@postgres:5432/db",
            REDIS_HOST="redis",
        )
        assert s.env == "production"

    def test_dev_env_does_not_require_secrets(self, monkeypatch):
        """Локальная разработка по-прежнему работает без секретов в .env."""
        for var in ("SECRET_KEY", "ADMIN_SECRET_KEY", "REFRESH_SECRET_KEY", "ENV"):
            monkeypatch.delenv(var, raising=False)
        s = config.Settings(_env_file=None, ENV="dev")
        assert s.secret_key == ""

    def test_missing_env_var_defaults_to_production_fail_safe(self, monkeypatch):
        """Если ENV вообще не задан — считаем что это прод (fail-safe), а не
        тихо разрешаем дев-режим по умолчанию."""
        for var in ("SECRET_KEY", "ADMIN_SECRET_KEY", "REFRESH_SECRET_KEY", "ENV"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(Exception):
            config.Settings(_env_file=None)


class TestProductionRequiresRealHosts:
    """Регресс: DATABASE_URL/REDIS_HOST дефолтились на localhost, и в
    отличие от секретов это не проверялось в проде вообще. Забытый
    .env.prod означал не громкую ошибку, а попытку приложения внутри
    контейнера подключиться к localhost (то есть к самому себе)."""

    def test_production_with_localhost_database_url_raises(self):
        with pytest.raises(Exception):
            config.Settings(
                _env_file=None,
                ENV="production",
                SECRET_KEY="a",
                ADMIN_SECRET_KEY="b",
                REFRESH_SECRET_KEY="c",
                REDIS_HOST="redis",
                # DATABASE_URL не задан -> дефолтный localhost
            )

    def test_production_with_localhost_redis_host_raises(self):
        with pytest.raises(Exception):
            config.Settings(
                _env_file=None,
                ENV="production",
                SECRET_KEY="a",
                ADMIN_SECRET_KEY="b",
                REFRESH_SECRET_KEY="c",
                DATABASE_URL="postgresql+asyncpg://user:pass@postgres:5432/db",
                # REDIS_HOST не задан -> дефолтный localhost
            )

    def test_production_with_real_hosts_succeeds(self):
        s = config.Settings(
            _env_file=None,
            ENV="production",
            SECRET_KEY="a",
            ADMIN_SECRET_KEY="b",
            REFRESH_SECRET_KEY="c",
            DATABASE_URL="postgresql+asyncpg://user:pass@postgres:5432/db",
            REDIS_HOST="redis",
        )
        assert "localhost" not in s.database_url
        assert s.redis_host == "redis"

    def test_dev_env_allows_localhost_hosts(self, monkeypatch):
        """В деве localhost — это нормальный, ожидаемый адрес."""
        for var in ("DATABASE_URL", "REDIS_HOST", "ENV"):
            monkeypatch.delenv(var, raising=False)
        s = config.Settings(_env_file=None, ENV="dev")
        assert "localhost" in s.database_url
        assert s.redis_host == "localhost"


class TestAdminAllowedIpsType:
    """Регресс: admin_allowed_ips был объявлен как str, но валидатор
    фактически возвращал list[str] — тип врал сам себе (с # type: ignore),
    и pydantic-settings падал при попытке распарсить обычную
    comma-separated строку как JSON для list-типа."""

    def test_parses_comma_separated_ips_into_list(self):
        s = config.Settings(
            _env_file=None,
            ADMIN_ALLOWED_IPS="1.2.3.4, 5.6.7.8,9.9.9.9",
            SECRET_KEY="a",
            ADMIN_SECRET_KEY="b",
            REFRESH_SECRET_KEY="c",
        )
        assert s.admin_allowed_ips == ["1.2.3.4", "5.6.7.8", "9.9.9.9"]
        assert isinstance(s.admin_allowed_ips, list)

    def test_empty_by_default(self):
        s = config.Settings(_env_file=None, SECRET_KEY="a", ADMIN_SECRET_KEY="b", REFRESH_SECRET_KEY="c", ENV="dev")
        assert s.admin_allowed_ips == []
