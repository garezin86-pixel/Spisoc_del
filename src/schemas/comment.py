from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
import html
import re


def _sanitize(text: str) -> str:
    """Экранирует HTML-теги и обрезает лишние пробелы."""
    # экранируем < > & " ' → &lt; &gt; &amp; и т.д.
    text = html.escape(text, quote=True)
    # убираем множественные пробелы/переносы
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()


class CommentUserSchema(BaseModel):
    id: int
    username: str

    model_config = ConfigDict(from_attributes=True)


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)

    @field_validator("content")
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        return _sanitize(v)


class CommentResponse(BaseModel):
    id: int
    content: str
    task_id: int
    created_at: datetime
    user: CommentUserSchema | None

    model_config = ConfigDict(from_attributes=True)
