import jwt
import structlog
from redis.asyncio import Redis

from src.core.config import REFRESH_TOKEN_EXPIRE_DAYS
from src.core.constants import INVALID_CREDENTIALS, USER_ALREADY_EXISTS
from src.core.exceptions import invalid_credentials, unauthorized, user_already_exists
from src.core.metrics import users_registered
from src.core.security import (
    create_access_token,
    create_mfa_token,
    create_refresh_token,
    decode_mfa_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from src.models.user import UserRole
from src.repositories.abstract import AbstractUserRepository
from src.schemas.token import TokenSchema
from src.schemas.user import UserLogin, UserRegister
from src.services.two_factor_service import TwoFactorService

logger = structlog.get_logger()

# Префикс ключа в Redis: refresh:{jti} → user_id
_REFRESH_PREFIX = "refresh:"


def _redis_key(jti: str) -> str:
    return f"{_REFRESH_PREFIX}{jti}"


class AuthService:
    """Сервис аутентификации и регистрации пользователей.

    Отвечает за проверку учётных данных и выдачу JWT-токенов.
    Не хранит состояния — каждый метод работает через переданный репозиторий.
    """

    def __init__(self, user_repo: AbstractUserRepository, redis: Redis):
        self.user_repo = user_repo
        self.redis = redis

    async def register(self, user: UserRegister):
        """Регистрирует нового пользователя.

        Зачем: создаёт учётную запись с хэшированным паролем и ролью «user».

        Side-effects:
            - Записывает событие user_registered в structlog.
            - Инкрементирует Prometheus-счётчик users_registered.

        Raises:
            HTTPException 400: если пользователь с таким именем уже существует.
        """
        existing = await self.user_repo.get_by_username(user.username)
        if existing:
            user_already_exists(USER_ALREADY_EXISTS)

        from src.models.user import UserModel

        new_user = UserModel(
            username=user.username,
            password_hash=hash_password(user.password),
            role="user",
        )
        created_user = await self.user_repo.create(new_user)
        await logger.ainfo("user_registered", user_id=created_user.id)
        users_registered.inc()
        return created_user

    async def _issue_tokens(self, db_user) -> TokenSchema:
        """Общий хвост выдачи пары access+refresh — переиспользуется обычным логином и login_with_2fa."""
        access_token = create_access_token({"sub": str(db_user.id), "role": db_user.role, "username": db_user.username})
        refresh_token, jti = create_refresh_token(db_user.id)

        await self.redis.set(
            _redis_key(jti),
            str(db_user.id),
            ex=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        )

        # Мягкое напоминание, а не блокировка: у admin/manager расширенные
        # права (аналитика, экспорт чужих задач, управление тегами), поэтому
        # 2FA для них особенно желательна — но жёстко требовать её при входе
        # рискованно (первый деплой без единой настроенной 2FA-учётки запер
        # бы единственного админа). Фронтенд показывает баннер, не мешает работать.
        requires_2fa_setup = db_user.role in (UserRole.admin, UserRole.manager) and not getattr(
            db_user, "totp_enabled", False
        )

        return TokenSchema(
            access_token=access_token,
            refresh_token=refresh_token,
            requires_2fa_setup=requires_2fa_setup,
            must_change_password=bool(getattr(db_user, "must_change_password", False)),
        )

    async def login(self, user: UserLogin) -> TokenSchema:
        """Проверяет пароль и либо выдаёт токены сразу, либо (если включена 2FA) — промежуточный mfa_token.

        Refresh token сохраняется в Redis с TTL = REFRESH_TOKEN_EXPIRE_DAYS.
        Ключ: refresh:{jti} → user_id (строка).
        """
        db_user = await self.user_repo.get_by_login(user.username)
        if not db_user:
            # Обратная совместимость: у пользователей, созданных до этой
            # фичи (или вручную через админку), login не проставлен —
            # они по-прежнему входят по username, как и раньше.
            db_user = await self.user_repo.get_by_username(user.username)
        if not db_user or not verify_password(user.password, db_user.password_hash):
            await logger.awarning("login_failed", username=user.username)
            invalid_credentials(INVALID_CREDENTIALS)
            raise

        if getattr(db_user, "totp_enabled", False):
            await logger.ainfo("login_password_ok_awaiting_2fa", user_id=db_user.id)
            return TokenSchema(mfa_required=True, mfa_token=create_mfa_token(db_user.id))

        await logger.ainfo("user_login", user_id=db_user.id)
        return await self._issue_tokens(db_user)

    async def login_with_2fa(self, mfa_token: str, code: str, two_factor_service: TwoFactorService) -> TokenSchema:
        """
        Второй шаг логина при включённой 2FA. two_factor_service передаётся
        параметром, а не хранится на self — AuthService не завязан на прямой
        AsyncSession (конструируется из абстрактного user_repo), а
        TwoFactorService нужен реальный session для проверки recovery-кодов.
        """
        try:
            payload = decode_mfa_token(mfa_token)
        except jwt.PyJWTError:
            unauthorized("Сессия входа истекла, войдите заново")
            raise

        user_id = int(payload["sub"])
        db_user = await self.user_repo.get_by_id(user_id)
        if not db_user or not db_user.is_active:
            unauthorized("Пользователь не найден или заблокирован")
            raise RuntimeError

        await two_factor_service.verify_login_code(db_user, code)

        await logger.ainfo("user_login_2fa", user_id=db_user.id)
        return await self._issue_tokens(db_user)

    async def refresh(self, refresh_token: str) -> TokenSchema:
        """Выдаёт новую пару токенов по валидному refresh token.

        Старый refresh token при этом инвалидируется (rotation):
        из Redis удаляется старый jti и записывается новый.
        Это защищает от повторного использования украденного токена.
        """
        try:
            payload = decode_refresh_token(refresh_token)
        except jwt.ExpiredSignatureError:
            unauthorized("Сессия истекла, войдите снова")
            raise
        except jwt.PyJWTError:
            unauthorized("Невалидный токен")
            raise

        # Проверяем что это именно refresh token, а не access
        if payload.get("type") != "refresh":
            unauthorized("Неверный тип токена")
            raise RuntimeError

        jti = payload.get("jti")
        user_id = payload.get("sub")

        if not jti or not user_id:
            unauthorized("Невалидный токен: отсутствуют обязательные поля")
            raise RuntimeError

        # Атомарно читаем и сразу удаляем jti (GETDEL) — раньше это были два
        # отдельных вызова (GET, затем DELETE), между которыми было окно гонки:
        # два параллельных запроса на refresh с одним и тем же токеном оба
        # проходили проверку "существует", и оба получали новую пару токенов.
        # GETDEL делает это одной атомарной командой Redis.
        stored = await self.redis.getdel(_redis_key(jti))
        if not stored:
            # Токен уже использован или отозван — возможна кража токена
            await logger.awarning("refresh_token_reuse", user_id=user_id, jti=jti)
            unauthorized("Токен отозван или уже использован")
            raise RuntimeError

        # Получаем пользователя и проверяем что он активен
        db_user = await self.user_repo.get_by_id(int(user_id))
        if not db_user or not db_user.is_active:
            unauthorized("Пользователь не найден или заблокирован")
            raise RuntimeError

        await logger.ainfo("token_refreshed", user_id=db_user.id)
        return await self._issue_tokens(db_user)

    async def logout(self, refresh_token: str) -> None:
        """Отзывает refresh token — удаляет jti из Redis.

        После этого токен нельзя использовать даже если он не истёк.
        Access token при этом остаётся валидным до своего истечения —
        это нормально, он короткоживущий (15-30 мин).
        """
        try:
            payload = decode_refresh_token(refresh_token)
            jti = payload.get("jti")
            if jti:
                await self.redis.delete(_redis_key(jti))
        except jwt.PyJWTError:
            pass  # невалидный токен при logout — не ошибка

        await logger.ainfo("user_logout")
