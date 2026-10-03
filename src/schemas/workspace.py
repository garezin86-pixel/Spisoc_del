# src/schemas/workspace.py
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.schemas.user import _validate_username


class RegisterRequest(BaseModel):
    """Самостоятельная регистрация в вебе.

    Ровно один из двух вариантов:
      * company_name  — создать новую компанию и стать её админом;
      * invite_token  — присоединиться к существующей компании (роль user).
    Поле role намеренно отсутствует: роль определяется только сценарием.
    """

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    company_name: str | None = Field(None, min_length=2, max_length=200)
    invite_token: str | None = Field(None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return _validate_username(v)

    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = re.sub(r"\s+", " ", v).strip()
        if len(v) < 2:
            raise ValueError("Название компании слишком короткое")
        return v

    @model_validator(mode="after")
    def exactly_one_scenario(self):
        if bool(self.company_name) == bool(self.invite_token):
            raise ValueError("Укажите либо company_name (новая компания), либо invite_token (приглашение)")
        return self


class InviteSchema(BaseModel):
    id: int
    token: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    # Готовые значения для ссылок; bot_link пуст, если имя бота ещё не известно.
    bot_start_param: str | None = None
    bot_link: str | None = None

    model_config = ConfigDict(from_attributes=True)
