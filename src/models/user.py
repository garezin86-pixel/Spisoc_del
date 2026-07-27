from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base
from src.models.group import user_group

if TYPE_CHECKING:
    from src.models.attachment_model import AttachmentModel
    from src.models.comment import CommentModel
    from src.models.group import GroupModel
    from src.models.personal_access_token import PersonalAccessTokenModel
    from src.models.project import ProjectModel
    from src.models.push_subscription import PushSubscriptionModel
    from src.models.two_factor_recovery_code import TwoFactorRecoveryCodeModel
    from src.models.webhook import WebhookModel


class UserRole(str, Enum):
    admin = "admin"
    manager = "manager"
    user = "user"

    def __str__(self) -> str:
        return self.value


class UserModel(Base):
    __tablename__ = "users"
    # Разрешает обычные (без Mapped[]) аннотации на этом классе — нужно для
    # pat_scope ниже, который специально НЕ должен быть колонкой БД.
    # См. https://sqlalche.me/e/20/zlpr
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(String, default=UserRole.user)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    # Токен для подписки на iCal-фид дедлайнов (см. src/routers/calendar_router.py).
    # Отдельный от PAT и JWT намеренно: календарные приложения (Google
    # Calendar, Outlook) периодически САМИ дёргают URL по расписанию и не
    # умеют слать заголовок Authorization — единственный практичный вариант
    # аутентификации для них — токен прямо в URL как query-параметр.
    # Поэтому у него узкое назначение (только чтение .ics, ничего больше) и
    # свой независимый жизненный цикл — скомпрометированный/утёкший токен
    # достаточно перевыпустить, не трогая PAT/пароль.
    calendar_feed_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # TOTP для двухфакторной аутентификации при веб-входе (см.
    # src/services/two_factor_service.py). totp_secret хранится в открытом
    # виде (не хэш!) — сервер должен уметь СЧИТАТЬ текущий код сам, чтобы
    # сверить его с тем, что ввёл пользователь, а из хэша код не
    # восстановить. Это тот же принцип, что и у webhook.secret — секрет,
    # который нужен нам для вычислений, а не для проверки хэша.
    # totp_enabled=False, пока secret не подтверждён первым верным кодом
    # (см. TwoFactorService.confirm_setup) — так что наличие totp_secret
    # само по себе ещё не значит, что 2FA реально требуется при входе.
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")

    # НЕ колонка БД — обычный Python-атрибут инстанса, выставляется в
    # authenticate_by_pat()/get_current_user() на время одного запроса, когда
    # аутентификация прошла по PAT-токену (см. src/services/pat_service.py и
    # src/core/dependencies.py:_enforce_pat_scope). None — либо JWT-сессия
    # (полный доступ), либо PAT ещё не проверялся.
    pat_scope: str | None = None

    assigned_tasks = relationship("SpisokModel", foreign_keys="[SpisokModel.user_id]", back_populates="user")
    authored_tasks = relationship(
        "SpisokModel",
        foreign_keys="[SpisokModel.author_id]",
        back_populates="author",
        cascade="all, delete",
    )
    groups: Mapped[list["GroupModel"]] = relationship(secondary=user_group, back_populates="users", lazy="selectin")
    comments: Mapped[list["CommentModel"]] = relationship(back_populates="user")

    # Relationships
    notification_settings = relationship("NotificationSettingsModel", back_populates="user", uselist=False)

    notification_logs = relationship("NotificationLogModel", back_populates="user", cascade="all, delete-orphan")
    personal_access_tokens: Mapped[list["PersonalAccessTokenModel"]] = relationship(
        "PersonalAccessTokenModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    push_subscriptions: Mapped[list["PushSubscriptionModel"]] = relationship(
        "PushSubscriptionModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    webhooks: Mapped[list["WebhookModel"]] = relationship(
        "WebhookModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    attachments: Mapped[list["AttachmentModel"]] = relationship(
        "AttachmentModel",
        back_populates="uploader",
    )
    two_factor_recovery_codes: Mapped[list["TwoFactorRecoveryCodeModel"]] = relationship(
        "TwoFactorRecoveryCodeModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_users_telegram_active", "telegram_id", "is_active"),)

    owned_projects: Mapped[list["ProjectModel"]] = relationship(
        "ProjectModel",
        foreign_keys="[ProjectModel.owner_id]",
        back_populates="owner",
        lazy="selectin",
    )
    projects: Mapped[list["ProjectModel"]] = relationship(
        "ProjectModel",
        secondary="project_member",
        back_populates="members",
        lazy="selectin",
    )

    def __str__(self):
        return f"{self.username}"
