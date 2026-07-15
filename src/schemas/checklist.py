# src/schemas/checklist.py
from pydantic import BaseModel, ConfigDict, Field


class ChecklistItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    order_index: int | None = Field(default=None, ge=0)


class ChecklistItemUpdate(BaseModel):
    """Все поля опциональны — частичное обновление одного пункта."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    is_done: bool | None = None
    order_index: int | None = Field(default=None, ge=0)


class ChecklistItemSchema(BaseModel):
    id: int
    task_id: int
    title: str
    is_done: bool
    order_index: int

    model_config = ConfigDict(from_attributes=True)


class ChecklistReorderItem(BaseModel):
    """Один элемент запроса на массовое переупорядочивание чек-листа."""

    id: int
    order_index: int = Field(..., ge=0)


class ChecklistReorderRequest(BaseModel):
    items: list[ChecklistReorderItem]
