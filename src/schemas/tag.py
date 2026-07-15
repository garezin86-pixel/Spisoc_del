# src/schemas/tag.py
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class TagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str = Field(default="#6b7280")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        v = v.strip().lstrip("#").strip()
        if not v:
            raise ValueError("Название тега не может быть пустым")
        return v

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        if not _HEX_COLOR_RE.match(v):
            raise ValueError("Цвет должен быть в формате #RRGGBB")
        return v


class TagSchema(BaseModel):
    id: int
    name: str
    color: str

    model_config = ConfigDict(from_attributes=True)


class TaskTagsUpdate(BaseModel):
    """Полная замена набора тегов на задаче (не добавление/удаление по одному)."""

    tag_ids: list[int] = Field(default_factory=list)
