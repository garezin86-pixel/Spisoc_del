# src/services/demo_data_service.py
"""Демо-данные: пример клиентов, сделок, задач и встреч, чтобы новый пользователь увидел систему «в деле».

Загружает и убирает только администратор. Демо-клиенты помечены `is_demo`, поэтому «Удалить демо» убирает ровно их
(вместе с контактами, сделками, взаимодействиями, задачами и встречами этих клиентов), а настоящие данные не трогает.
Все операции — одной транзакцией: либо всё, либо ничего.

Даты считаются от «сегодня», чтобы демо выглядело живым: есть просроченная задача, клиенты, которым «пора позвонить»,
ближайшие встречи, выигранная и проигранная сделки.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

import structlog
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.client import ClientModel, ContactModel
from src.models.deal import DEFAULT_CURRENCY, DealModel, StageKind
from src.models.enums import TaskPriority, TaskStatus
from src.models.interaction import InteractionModel, InteractionType
from src.models.scheduled_event import EventStatus, EventType, ScheduledEventModel
from src.models.task import SpisokModel
from src.models.user import UserModel, UserRole
from src.repositories.deal_repository import DealRepository
from src.services.deal_service import DEFAULT_PIPELINE_NAME, DEFAULT_STAGES

logger = structlog.get_logger()


@dataclass
class DemoCounts:
    clients: int = 0
    contacts: int = 0
    deals: int = 0
    interactions: int = 0
    tasks: int = 0
    events: int = 0


# (название, тип, телефон, email, адрес, заметки, дата рождения, пол, «связаться через N дней» (<=0 — пора))
_CLIENTS: list[tuple[str, str, str, str | None, str, str, date | None, str | None, int | None]] = [
    (
        "Альфа-Строй",
        "company",
        "+380500000001",
        "office@alfa-stroy.example",
        "Харьков, ул. Центральная, 12",
        "Строительная компания. Берут материалы партиями, важны сроки поставки.",
        None,
        None,
        -2,
    ),
    (
        "ТехноМаркет",
        "company",
        "+380500000002",
        "sales@technomarket.example",
        "Киев, пр. Победы, 45",
        "Сеть магазинов электроники. Решение принимает закупщик.",
        None,
        None,
        0,
    ),
    (
        "Зелёный Двор",
        "company",
        "+380500000003",
        "info@zelenyi-dvor.example",
        "Полтава, ул. Садовая, 3",
        "Садовый центр. Сезонные заказы, весной активность выше.",
        None,
        None,
        7,
    ),
    (
        "АгроПартнёр",
        "company",
        "+380500000004",
        "zakaz@agropartner.example",
        "Сумы, ул. Заводская, 8",
        "Агрокомпания. Интересует оптовая цена.",
        None,
        None,
        14,
    ),
    (
        "Логистик-Плюс",
        "company",
        "+380500000005",
        "dispatch@logistik-plus.example",
        "Днепр, ул. Новая, 27",
        "Транспортная компания. Хотят годовой договор.",
        None,
        None,
        -5,
    ),
    (
        "Кофейня «Утро»",
        "company",
        "+380500000006",
        "hello@utro-coffee.example",
        "Львов, ул. Школьная, 5",
        "Небольшая сеть кофеен. Постоянный клиент.",
        None,
        None,
        30,
    ),
    (
        "МедЦентр «Здоровье»",
        "company",
        "+380500000007",
        "admin@zdorovie.example",
        "Одесса, пр. Мира, 19",
        "Частная клиника. Выбирали между нами и конкурентом.",
        None,
        None,
        None,
    ),
    (
        "Мария Кравченко",
        "person",
        "+380500000011",
        "m.kravchenko@example.org",
        "Харьков",
        "Пришла по рекомендации.",
        date(1988, 4, 17),
        "female",
        1,
    ),
    (
        "Олег Сидоренко",
        "person",
        "+380500000012",
        None,
        "Киев",
        "Просил перезвонить после 15:00.",
        date(1979, 11, 2),
        "male",
        10,
    ),
    (
        "Наталья Бондаренко",
        "person",
        "+380500000013",
        "n.bondarenko@example.org",
        "Полтава",
        "",
        date(1992, 8, 23),
        "female",
        None,
    ),
    (
        "Виктор Шевченко",
        "person",
        "+380500000014",
        None,
        "Винница",
        "Интересовался сервисным пакетом.",
        date(1985, 1, 30),
        "male",
        -1,
    ),
    (
        "Анна Мельник",
        "person",
        "+380500000015",
        "a.melnik@example.org",
        "Чернигов",
        "Новый контакт с сайта.",
        date(1995, 6, 9),
        "female",
        3,
    ),
]

# клиент (индекс) → контакты (имя, должность, телефон, email)
_CONTACTS: dict[int, list[tuple[str, str, str, str]]] = {
    0: [
        ("Сергей Коваленко", "Директор", "+380500000101", "s.kovalenko@alfa-stroy.example"),
        ("Ирина Лисенко", "Бухгалтер", "+380500000102", "buh@alfa-stroy.example"),
    ],
    1: [("Дмитрий Орлов", "Закупщик", "+380500000103", "d.orlov@technomarket.example")],
    4: [("Павел Гончар", "Руководитель отдела продаж", "+380500000104", "p.gonchar@logistik-plus.example")],
    6: [("Елена Ткаченко", "Главный врач", "+380500000105", "e.tkachenko@zdorovie.example")],
}

# (клиент, название, сумма, «шаг» стадии: номер открытой стадии | "won" | "lost", ожидаемое закрытие через N дней)
_DEALS: list[tuple[int, str, int, int | str, int | None]] = [
    (0, "Поставка материалов на объект", 185000, 2, 14),
    (1, "Оборудование для нового магазина", 94000, 1, 21),
    (2, "Ландшафтный проект", 62000, 0, 30),
    (4, "Годовой договор на логистику", 240000, 3, 45),
    (5, "Кофемашины (2 шт.)", 78500, "won", None),
    (6, "Абонемент на обслуживание", 120000, "lost", None),
    (7, "Консультация и подбор", 8500, 0, 7),
    (8, "Сервисный пакет", 15000, 1, 10),
]

# (клиент, тип, дней назад, содержание)
_INTERACTIONS: list[tuple[int, InteractionType, int, str]] = [
    (0, InteractionType.call, 9, "Обсудили объём и сроки поставки. Просят КП до конца недели."),
    (0, InteractionType.email, 4, "Отправили предварительный расчёт."),
    (1, InteractionType.meeting, 6, "Встреча в офисе: показали каталог, закупщик взял паузу на согласование."),
    (2, InteractionType.message, 3, "Написали в мессенджере, ждём ответа по смете."),
    (4, InteractionType.call, 12, "Первый звонок. Интересует годовой договор и скидка за объём."),
    (4, InteractionType.note, 8, "Внутренняя заметка: конкурент предложил на 5% дешевле."),
    (5, InteractionType.meeting, 20, "Подписали договор на кофемашины."),
    (6, InteractionType.call, 30, "Клиника выбрала другого поставщика, причина — цена."),
    (7, InteractionType.call, 2, "Рассказали про услугу, договорились созвониться."),
    (10, InteractionType.email, 15, "Отправили описание сервисного пакета."),
]

# (клиент, название, срок в днях от сегодня, приоритет, статус)
_TASKS: list[tuple[int, str, int, TaskPriority, TaskStatus]] = [
    (0, "Отправить коммерческое предложение", 1, TaskPriority.high, TaskStatus.todo),
    (1, "Позвонить закупщику и уточнить решение", -1, TaskPriority.medium, TaskStatus.todo),
    (4, "Подготовить проект договора", 3, TaskPriority.high, TaskStatus.in_progress),
    (2, "Согласовать смету", 7, TaskPriority.low, TaskStatus.backlog),
    (7, "Перезвонить по итогам консультации", 2, TaskPriority.medium, TaskStatus.todo),
    (5, "Выставить счёт за кофемашины", -4, TaskPriority.medium, TaskStatus.done),
]

# (клиент, тип, через сколько дней, час, длительность мин, название)
_EVENTS: list[tuple[int, EventType, int, int, int, str]] = [
    (0, EventType.meeting, 2, 11, 60, "Встреча по поставке материалов"),
    (1, EventType.call, 1, 15, 15, "Звонок: решение по оборудованию"),
    (4, EventType.meeting, 5, 10, 45, "Обсуждение годового договора"),
]


def _require_admin(user: UserModel) -> None:
    if user.role != UserRole.admin:
        raise HTTPException(403, "Загружать и удалять демо-данные может только admin")


async def _demo_clients(session: AsyncSession) -> list[ClientModel]:
    result = await session.execute(
        select(ClientModel).where(ClientModel.is_demo.is_(True), ClientModel.not_deleted_filter())
    )
    return list(result.scalars().all())


async def demo_status(session: AsyncSession) -> dict:
    count = await session.scalar(
        select(func.count())
        .select_from(ClientModel)
        .where(ClientModel.is_demo.is_(True), ClientModel.not_deleted_filter())
    )
    return {"loaded": bool(count), "clients": int(count or 0)}


async def load_demo(session: AsyncSession, current_user: UserModel, today: date | None = None) -> dict:
    """Создаёт демо-клиентов со сделками, взаимодействиями, задачами и встречами; владелец всего — current_user."""
    _require_admin(current_user)
    if (await demo_status(session))["loaded"]:
        raise HTTPException(409, "Демо-данные уже загружены. Сначала удалите их.")

    deals_repo = DealRepository(session)
    deals_repo.set_audit_user(current_user.id)
    today = today or date.today()
    now = datetime.now(timezone.utc)
    counts = DemoCounts()

    # Воронка: своя (если уже настроена) или стандартная.
    pipeline = await deals_repo.get_default_pipeline()
    if pipeline is None:
        pipeline = await deals_repo.create_pipeline_with_stages(
            DEFAULT_PIPELINE_NAME, [(name, kind, None) for name, kind in DEFAULT_STAGES]
        )
    stages = await deals_repo.list_stages(pipeline.id)
    open_stages = [s for s in stages if s.kind == StageKind.open.value]
    won = next((s for s in stages if s.kind == StageKind.won.value), None)
    lost = next((s for s in stages if s.kind == StageKind.lost.value), None)
    if not open_stages:
        raise HTTPException(409, "В воронке нет стадий «в работе» — демо-сделки некуда положить")

    clients: list[ClientModel] = []
    for name, kind, phone, email, address, notes, birth, gender, contact_in in _CLIENTS:
        client = ClientModel(
            name=name,
            client_type=kind,
            phone=phone,
            email=email,
            address=address,
            notes=notes or None,
            birth_date=birth,
            gender=gender,
            next_contact_at=(today + timedelta(days=contact_in)) if contact_in is not None else None,
            owner_id=current_user.id,
            is_demo=True,
        )
        session.add(client)
        clients.append(client)
    await session.flush()
    counts.clients = len(clients)

    contact_by_client: dict[int, ContactModel] = {}
    for index, people in _CONTACTS.items():
        for person_name, position, phone, email in people:
            contact = ContactModel(
                client_id=clients[index].id, name=person_name, position=position, phone=phone, email=email
            )
            session.add(contact)
            contact_by_client.setdefault(index, contact)
            counts.contacts += 1
    await session.flush()

    position_in_stage: dict[int, int] = {}
    for index, title, amount, step, close_in in _DEALS:
        if step == "won":
            stage = won or open_stages[-1]
        elif step == "lost":
            stage = lost or open_stages[-1]
        else:
            stage = open_stages[min(int(step), len(open_stages) - 1)]
        closed = stage.kind in (StageKind.won.value, StageKind.lost.value)
        position_in_stage[stage.id] = position_in_stage.get(stage.id, 0) + 1
        session.add(
            DealModel(
                client_id=clients[index].id,
                stage_id=stage.id,
                title=title,
                amount=amount,
                currency=DEFAULT_CURRENCY,
                owner_id=current_user.id,
                expected_close_date=(today + timedelta(days=close_in)) if close_in is not None else None,
                closed_at=(now - timedelta(days=5)) if closed else None,
                lost_reason="Выбрали другого поставщика: цена" if stage.kind == StageKind.lost.value else None,
                position=position_in_stage[stage.id],
            )
        )
        counts.deals += 1

    for index, kind, days_ago, summary in _INTERACTIONS:
        contact = contact_by_client.get(index)
        session.add(
            InteractionModel(
                client_id=clients[index].id,
                contact_id=contact.id if contact else None,
                type=kind.value,
                occurred_at=now - timedelta(days=days_ago),
                summary=summary,
                author_id=current_user.id,
            )
        )
        counts.interactions += 1

    for index, title, due_in, priority, status in _TASKS:
        done = status == TaskStatus.done
        session.add(
            SpisokModel(
                title=title,
                user_id=current_user.id,
                author_id=current_user.id,
                client_id=clients[index].id,
                deadline=datetime.combine(
                    today + timedelta(days=due_in), datetime.min.time(), tzinfo=timezone.utc
                ).replace(hour=15),
                priority=priority,
                status=status,
                completed_at=(now - timedelta(days=4)) if done else None,
            )
        )
        counts.tasks += 1

    for index, kind, in_days, hour, minutes, title in _EVENTS:
        starts = datetime.combine(today + timedelta(days=in_days), datetime.min.time(), tzinfo=timezone.utc).replace(
            hour=hour
        )
        session.add(
            ScheduledEventModel(
                client_id=clients[index].id,
                type=kind.value,
                title=title,
                starts_at=starts,
                duration_minutes=minutes,
                assignee_id=current_user.id,
                status=EventStatus.planned.value,
                created_by_id=current_user.id,
            )
        )
        counts.events += 1

    await session.commit()
    await logger.ainfo("demo_loaded", user_id=current_user.id, clients=counts.clients)
    return asdict(counts)


async def remove_demo(session: AsyncSession, current_user: UserModel) -> dict:
    """Убирает демо-клиентов и всё, что к ним привязано (мягкое удаление, одна транзакция). Настоящее не трогает."""
    _require_admin(current_user)
    session.info["audit_user_id"] = current_user.id
    counts = DemoCounts()
    clients = await _demo_clients(session)
    if not clients:
        return asdict(counts)
    ids = [c.id for c in clients]

    def alive(model):
        return select(model).where(model.client_id.in_(ids), model.not_deleted_filter())

    for model, field in (
        (InteractionModel, "interactions"),
        (DealModel, "deals"),
        (ContactModel, "contacts"),
        (SpisokModel, "tasks"),
        (ScheduledEventModel, "events"),
    ):
        for row in (await session.execute(alive(model))).scalars().all():
            row.soft_delete(session)
            setattr(counts, field, getattr(counts, field) + 1)
    for client in clients:
        client.soft_delete(session)
    counts.clients = len(clients)
    await session.commit()
    await logger.ainfo("demo_removed", user_id=current_user.id, clients=counts.clients)
    return asdict(counts)
