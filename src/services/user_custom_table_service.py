# src/services/user_custom_table_service.py
"""Самостоятельные таблицы пользователей (Smart Tables, этапы 4.1 и 4.5): таблицы, колонки, участники.

Права:
  * создать таблицу может любой пользователь компании (владелец — создатель); лимит таблиц на компанию;
  * видимость: private — владелец, admin, manager; shared — вся компания; restricted — они же плюс участники
    (выбранные пользователи). Недоступную таблицу не видно совсем (404);
  * строки: в shared правит любой, кто видит; в restricted — участник с can_edit (остальные участники только читают;
    без права на правку — 403); в private — владелец, admin, manager;
  * менять настройки, структуру (колонки), участников и удалять таблицу — владелец, admin, manager (не делегируется);
  * сменить владельца — только admin и manager (новый владелец должен быть пользователем этой компании).
Таблица принадлежит компании, а не человеку: при удалении владельца `owner_id` обнуляется, данные остаются.
Тип колонки после создания не меняется. Удаление таблиц и колонок мягкое.
"""

import structlog
from fastapi import HTTPException

from src.models.user import UserModel, UserRole
from src.models.user_custom_table import (
    UserCustomTableColumnModel,
    UserCustomTableMemberModel,
    UserCustomTableModel,
    UserTableVisibility,
)
from src.repositories.user_custom_table_repository import UserCustomTableRepository
from src.repositories.users_repository import UserRepository
from src.schemas.user_custom_table import (
    MAX_COLUMNS_PER_TABLE,
    MAX_TABLE_MEMBERS,
    UserTableColumnCreate,
    UserTableColumnSchema,
    UserTableColumnUpdate,
    UserTableCreate,
    UserTableListItem,
    UserTableMemberSchema,
    UserTableMembersUpdate,
    UserTableSchema,
    UserTableUpdate,
)

logger = structlog.get_logger()

MAX_TABLES_PER_WORKSPACE = 100


def _is_manager(user: UserModel) -> bool:
    return user.role in (UserRole.admin, UserRole.manager)


def can_manage_table(table: UserCustomTableModel, user: UserModel) -> bool:
    """Настройки, колонки, участники, удаление: владелец, admin, manager."""
    return _is_manager(user) or table.owner_id == user.id


def can_view_table(table: UserCustomTableModel, user: UserModel, member_can_edit: bool | None = None) -> bool:
    """Общую таблицу видит вся компания; личную — владелец, admin, manager; с ограниченным доступом — они же и
    участники. `member_can_edit` — None, если пользователь не участник, иначе его право на правку строк."""
    if can_manage_table(table, user) or table.visibility == UserTableVisibility.shared.value:
        return True
    return table.visibility == UserTableVisibility.restricted.value and member_can_edit is not None


def can_edit_table_rows(table: UserCustomTableModel, user: UserModel, member_can_edit: bool | None = None) -> bool:
    """Строки правит тот, кто видит таблицу, кроме участников только для чтения (restricted, can_edit=false)."""
    if not can_view_table(table, user, member_can_edit):
        return False
    if can_manage_table(table, user) or table.visibility != UserTableVisibility.restricted.value:
        return True
    return bool(member_can_edit)


class UserCustomTableService:
    def __init__(self, repo: UserCustomTableRepository, user_repo: UserRepository):
        self.repo = repo
        self.user_repo = user_repo

    # ── доступ ───────────────────────────────────────────────────────────────
    async def _member_can_edit(self, table: UserCustomTableModel, user: UserModel) -> bool | None:
        """None — не участник (или участие не нужно); иначе право участника на правку строк."""
        if table.visibility != UserTableVisibility.restricted.value or can_manage_table(table, user):
            return None
        member = await self.repo.get_member(table.id, user.id)
        return None if member is None else member.can_edit

    async def _visible_table_or_404(self, table_id: int, user: UserModel) -> UserCustomTableModel:
        table = await self.repo.get_table(table_id)
        # скрытая таблица неотличима от несуществующей
        if table is None or not can_view_table(table, user, await self._member_can_edit(table, user)):
            raise HTTPException(404, "Таблица не найдена")
        return table

    async def get_visible_table(self, table_id: int, user: UserModel) -> UserCustomTableModel:
        """Таблица, которую пользователь видит (иначе 404). Читает строки тот, кто видит таблицу."""
        return await self._visible_table_or_404(table_id, user)

    async def get_table_for_row_edit(self, table_id: int, user: UserModel) -> UserCustomTableModel:
        """Таблица, в строках которой пользователь может писать: 404, если не видит; 403, если только читает."""
        table = await self._visible_table_or_404(table_id, user)
        if not can_edit_table_rows(table, user, await self._member_can_edit(table, user)):
            raise HTTPException(403, "В этой таблице у вас доступ только на чтение")
        return table

    async def list_columns(self, table_id: int) -> list[UserCustomTableColumnModel]:
        return await self.repo.list_columns(table_id)

    async def _managed_table_or_error(self, table_id: int, user: UserModel) -> UserCustomTableModel:
        table = await self._visible_table_or_404(table_id, user)
        if not can_manage_table(table, user):
            raise HTTPException(403, "Менять таблицу может владелец, admin или manager")
        return table

    async def _schema(self, table: UserCustomTableModel, user: UserModel) -> UserTableSchema:
        columns = await self.repo.list_columns(table.id)
        member_can_edit = await self._member_can_edit(table, user)
        return UserTableSchema(
            id=table.id,
            name=table.name,
            description=table.description,
            icon=table.icon,
            visibility=table.visibility,
            owner_id=table.owner_id,
            can_edit_rows=can_edit_table_rows(table, user, member_can_edit),
            can_manage=can_manage_table(table, user),
            columns=[UserTableColumnSchema.model_validate(c) for c in columns],
            created_at=table.created_at,
            updated_at=table.updated_at,
        )

    # ── таблицы ──────────────────────────────────────────────────────────────
    async def list_tables(self, user: UserModel) -> list[UserTableListItem]:
        tables = await self.repo.list_tables(None if _is_manager(user) else user.id)
        counts = await self.repo.columns_count_by_table([t.id for t in tables])
        member_access = await self.repo.member_access(user.id)
        return [
            UserTableListItem(
                id=t.id,
                name=t.name,
                description=t.description,
                icon=t.icon,
                visibility=t.visibility,
                owner_id=t.owner_id,
                columns_count=counts.get(t.id, 0),
                can_edit_rows=can_edit_table_rows(t, user, member_access.get(t.id)),
                can_manage=can_manage_table(t, user),
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in tables
        ]

    async def get_table(self, table_id: int, user: UserModel) -> UserTableSchema:
        return await self._schema(await self._visible_table_or_404(table_id, user), user)

    async def create_table(self, data: UserTableCreate, user: UserModel) -> UserTableSchema:
        if await self.repo.count_tables() >= MAX_TABLES_PER_WORKSPACE:
            raise HTTPException(409, f"В компании не больше {MAX_TABLES_PER_WORKSPACE} самостоятельных таблиц")
        self.repo.set_audit_user(user.id)
        table = UserCustomTableModel(
            name=data.name,
            description=data.description,
            icon=data.icon,
            visibility=data.visibility,
            owner_id=user.id,
        )
        columns = [
            UserCustomTableColumnModel(name=c.name, data_type=c.data_type, options=c.options, position=i)
            for i, c in enumerate(data.columns)
        ]
        created = await self.repo.create_table(table, columns)
        await logger.ainfo("user_table_created", table_id=created.id, columns=len(columns))
        return await self._schema(created, user)

    async def update_table(self, table_id: int, data: UserTableUpdate, user: UserModel) -> UserTableSchema:
        table = await self._managed_table_or_error(table_id, user)
        changes = data.model_dump(exclude_unset=True)
        if "owner_id" in changes:
            if not _is_manager(user):
                raise HTTPException(403, "Сменить владельца таблицы может только admin или manager")
            # get_by_id идёт через scoped-сессию: пользователь другой компании → None
            if await self.user_repo.get_by_id(changes["owner_id"]) is None:
                raise HTTPException(404, "Пользователь не найден")
        self.repo.set_audit_user(user.id)
        for key, value in changes.items():
            setattr(table, key, value)
        updated = await self.repo.update_table(table)
        await logger.ainfo("user_table_updated", table_id=table_id)
        return await self._schema(updated, user)

    async def delete_table(self, table_id: int, user: UserModel) -> dict:
        table = await self._managed_table_or_error(table_id, user)
        self.repo.set_audit_user(user.id)
        await self.repo.soft_delete_table(table)
        await logger.ainfo("user_table_deleted", table_id=table_id)
        return {"message": f"User table {table_id} deleted"}

    # ── колонки ──────────────────────────────────────────────────────────────
    async def _column_or_404(self, table_id: int, column_id: int) -> UserCustomTableColumnModel:
        column = await self.repo.get_column(table_id, column_id)
        if column is None:
            raise HTTPException(404, "Колонка не найдена")
        return column

    async def _require_unique_column_name(self, table_id: int, name: str, exclude_id: int | None = None) -> None:
        key = name.casefold()
        for other in await self.repo.list_columns(table_id):
            if other.id != exclude_id and other.name.casefold() == key:
                raise HTTPException(409, f"Колонка «{other.name}» уже есть")

    async def add_column(self, table_id: int, data: UserTableColumnCreate, user: UserModel) -> UserTableColumnSchema:
        table = await self._managed_table_or_error(table_id, user)
        if len(await self.repo.list_columns(table.id)) >= MAX_COLUMNS_PER_TABLE:
            raise HTTPException(409, f"В таблице не больше {MAX_COLUMNS_PER_TABLE} колонок")
        await self._require_unique_column_name(table.id, data.name)
        self.repo.set_audit_user(user.id)
        column = UserCustomTableColumnModel(
            table_id=table.id,
            name=data.name,
            data_type=data.data_type,
            options=data.options,
            position=await self.repo.max_column_position(table.id) + 1,
        )
        created = await self.repo.create_column(column)
        await logger.ainfo("user_table_column_created", table_id=table.id, column_id=created.id)
        return UserTableColumnSchema.model_validate(created)

    async def update_column(
        self, table_id: int, column_id: int, data: UserTableColumnUpdate, user: UserModel
    ) -> UserTableColumnSchema:
        table = await self._managed_table_or_error(table_id, user)
        column = await self._column_or_404(table.id, column_id)
        changes = data.model_dump(exclude_unset=True)
        if "options" in changes and column.data_type != "select":
            raise HTTPException(422, "Значения списка есть только у колонки типа select")
        if "name" in changes:
            await self._require_unique_column_name(table.id, changes["name"], exclude_id=column.id)
        self.repo.set_audit_user(user.id)
        for key, value in changes.items():
            setattr(column, key, value)
        updated = await self.repo.update_column(column)
        await logger.ainfo("user_table_column_updated", table_id=table.id, column_id=column_id)
        return UserTableColumnSchema.model_validate(updated)

    async def delete_column(self, table_id: int, column_id: int, user: UserModel) -> dict:
        table = await self._managed_table_or_error(table_id, user)
        column = await self._column_or_404(table.id, column_id)
        self.repo.set_audit_user(user.id)
        await self.repo.soft_delete_column(column)
        await logger.ainfo("user_table_column_deleted", table_id=table.id, column_id=column_id)
        return {"message": f"Column {column_id} deleted"}

    # ── участники (ограниченный доступ) ──────────────────────────────────────
    async def _member_schemas(self, table_id: int) -> list[UserTableMemberSchema]:
        result = []
        for member in await self.repo.list_members(table_id):
            account = await self.user_repo.get_by_id(member.user_id)
            result.append(
                UserTableMemberSchema(
                    user_id=member.user_id, username=account.username if account else None, can_edit=member.can_edit
                )
            )
        return result

    async def list_members(self, table_id: int, user: UserModel) -> list[UserTableMemberSchema]:
        """Список участников видят только те, кто управляет таблицей (владелец, admin, manager)."""
        table = await self._managed_table_or_error(table_id, user)
        return await self._member_schemas(table.id)

    async def set_members(
        self, table_id: int, data: UserTableMembersUpdate, user: UserModel
    ) -> list[UserTableMemberSchema]:
        """Заменяет список участников целиком. Доступ получают только при видимости restricted; список можно
        подготовить заранее. Каждый участник должен быть пользователем этой компании."""
        table = await self._managed_table_or_error(table_id, user)
        if len(data.members) > MAX_TABLE_MEMBERS:
            raise HTTPException(409, f"Не больше {MAX_TABLE_MEMBERS} участников")
        for item in data.members:
            if await self.user_repo.get_by_id(item.user_id) is None:  # scoped: чужая компания → None
                raise HTTPException(422, f"Пользователь с id {item.user_id} не найден")

        self.repo.set_audit_user(user.id)
        existing = {m.user_id: m for m in await self.repo.list_members(table.id, include_deleted=True)}
        wanted = {item.user_id: item.can_edit for item in data.members}
        for user_id, can_edit in wanted.items():
            member = existing.get(user_id)
            if member is None:
                self.repo.add_member(UserCustomTableMemberModel(table_id=table.id, user_id=user_id, can_edit=can_edit))
                continue
            if member.is_deleted:
                member.restore(self.repo.session)
            if member.can_edit != can_edit:
                member.can_edit = can_edit
        for user_id, member in existing.items():
            if user_id not in wanted and not member.is_deleted:
                member.soft_delete(self.repo.session)
        await self.repo.commit()
        await logger.ainfo("user_table_members_set", table_id=table.id, members=len(wanted))
        return await self._member_schemas(table.id)
