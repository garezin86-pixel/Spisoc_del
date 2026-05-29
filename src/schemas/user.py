from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal
import re


def _validate_username(v: str) -> str:
    if not re.match(r"^[a-zA-Zа-яА-ЯёЁ0-9_ ]+$", v):
        raise ValueError("Имя пользователя содержит недопустимые символы")
    return v.strip()


class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    role: Literal["user", "admin", "manager"] = "user"

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return _validate_username(v)


class UserLogin(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)


class UserSchema(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    telegram_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class UserSchemaForTask(BaseModel):
    id: int
    username: str

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    username: str | None = Field(None, min_length=3, max_length=50)
    password: str | None = Field(None, min_length=6, max_length=100)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_username(v)
