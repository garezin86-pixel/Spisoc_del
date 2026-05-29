from src.core import config


def test_config_values_are_valid():
    assert isinstance(config.ACCESS_TOKEN_EXPIRE_MINUTES, int)
    assert config.ACCESS_TOKEN_EXPIRE_MINUTES > 0
    assert isinstance(config.DATABASE_URL, str)
    assert config.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert isinstance(config.SECRET_KEY, str)
    assert config.SECRET_KEY != ""
