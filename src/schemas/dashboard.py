# src/schemas/dashboard.py
from datetime import date, datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

from src.models.enums import TaskPriority, TaskStatus
from src.models.scheduled_event import EventStatus, EventType
from src.schemas.deal import PipelineSummary

T = TypeVar("T")


class DashboardList(BaseModel, Generic[T]):
    """Секция дашборда: первые `items` и общее количество `total` (если не все поместились в лимит)."""

    total: int
    items: List[T]


class DashboardTask(BaseModel):
    id: int
    title: str
    deadline: Optional[datetime] = None
    priority: TaskPriority
    status: TaskStatus
    project_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class DashboardClient(BaseModel):
    id: int
    name: str
    client_type: str
    last_contact_at: Optional[datetime] = None  # None — контактов ещё не было
    days_since_contact: int  # от последнего контакта, а если его не было — от создания клиента
    next_contact_at: Optional[date] = None


class DashboardEvent(BaseModel):
    id: int
    client_id: int
    client_name: str
    type: EventType
    title: Optional[str] = None
    starts_at: datetime
    duration_minutes: Optional[int] = None
    status: EventStatus


class DashboardSchema(BaseModel):
    """Рабочий стол менеджера: что делать сегодня. Все секции — про `user_id`."""

    user_id: int
    generated_at: datetime
    tz: str  # часовой пояс, по которому считалось «сегодня»
    today: date
    stale_days: int  # порог секции stale_clients
    tasks_today: DashboardList[DashboardTask]
    overdue_tasks: DashboardList[DashboardTask]
    stale_clients: DashboardList[DashboardClient]
    upcoming_events: DashboardList[DashboardEvent]
    pipeline: PipelineSummary
    cached: bool = False  # True — ответ из кэша (не старше 45 секунд, см. generated_at)
