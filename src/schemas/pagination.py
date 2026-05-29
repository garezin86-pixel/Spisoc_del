from typing import Generic, List, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Параметры пагинации"""

    page: int = Field(default=1, ge=1, description="Номер страницы")
    size: int = Field(
        default=20, ge=1, le=100, description="Размер страницы (макс. 100)"
    )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class PaginatedResponse(BaseModel, Generic[T]):
    """Стандартный ответ с пагинацией"""

    items: List[T]
    total: int
    page: int
    size: int
    pages: int

    model_config = {"from_attributes": True}

    # Для удобства можно добавить метод
    @classmethod
    def create(cls, items: List[T], total: int, page: int, size: int):
        pages = (total + size - 1) // size if size > 0 else 0
        return cls(items=items, total=total, page=page, size=size, pages=pages)
