"""
Unit-тесты: модуль безопасности (хеши паролей, JWT).
Не требуют БД.
"""

import pytest
from datetime import datetime, timezone
import jwt

from src.core.security import hash_password, verify_password, create_access_token
from src.core.config import SECRET_KEY, ALGORITHM


class TestPasswordHashing:
    def test_hash_returns_string(self):
        result = hash_password("mypassword")
        assert isinstance(result, str)

    def test_hash_is_not_plain_text(self):
        pwd = "mypassword"
        assert hash_password(pwd) != pwd

    def test_same_password_gives_different_hashes(self):
        """bcrypt использует salt — два хеша одного пароля должны отличаться."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2

    def test_verify_correct_password(self):
        pwd = "correct_password"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_verify_empty_password_fails(self):
        hashed = hash_password("real_password")
        assert verify_password("", hashed) is False

    def test_verify_similar_password_fails(self):
        hashed = hash_password("password123")
        assert verify_password("password124", hashed) is False


class TestJWT:
    def test_create_token_returns_string(self):
        token = create_access_token({"sub": "1"})
        assert isinstance(token, str)

    def test_token_contains_sub(self):
        token = create_access_token({"sub": "42"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "42"

    def test_token_contains_exp(self):
        token = create_access_token({"sub": "1"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_token_expires_in_future(self):
        token = create_access_token({"sub": "1"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert exp > datetime.now(timezone.utc)

    def test_invalid_token_raises(self):
        import jwt

        with pytest.raises(jwt.PyJWTError):
            jwt.decode("invalid.token.here", SECRET_KEY, algorithms=[ALGORITHM])

    def test_token_with_wrong_secret_raises(self):
        import jwt

        token = create_access_token({"sub": "1"})
        with pytest.raises(jwt.PyJWTError):
            jwt.decode(token, "wrong_secret", algorithms=[ALGORITHM])
