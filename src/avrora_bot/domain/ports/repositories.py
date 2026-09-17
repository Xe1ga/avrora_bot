"""Порты (Protocol) репозиториев — контракты слоя хранения.

Слой приложения зависит от этих абстракций, а не от SQLAlchemy. Реализации
находятся в ``adapters/database/repositories.py``.
"""

from datetime import date
from typing import Protocol

from avrora_bot.domain.entities import (
    ActionLogEntry,
    CalendarEvent,
    ConsentRecord,
    LegalDocument,
    OneTimePayment,
    ScheduleSlot,
    Subscription,
    SubscriptionPayment,
    Tariff,
    User,
)
from avrora_bot.domain.enums import (
    LegalDocumentKind,
    RoleName,
    TariffKind,
    UserStatus,
)
from avrora_bot.domain.value_objects import MonthPeriod


class UserRepository(Protocol):
    """Хранилище пользователей."""

    async def get_by_vk_id(self, vk_id: int | None) -> User | None: ...

    async def get_by_id(self, user_id: int) -> User | None: ...

    async def add(self, user: User) -> User: ...

    async def update(self, user: User) -> None: ...

    async def list_by_status(self, status: UserStatus) -> list[User]: ...

    async def list_all(self) -> list[User]: ...


class LegalDocumentRepository(Protocol):
    """Версии юридических документов (append-only)."""

    async def add(self, document: LegalDocument) -> LegalDocument: ...

    async def get(self, document_id: int) -> LegalDocument | None: ...

    async def get_by_version(
        self, kind: LegalDocumentKind, version: str
    ) -> LegalDocument | None: ...

    async def current(
        self, kind: LegalDocumentKind
    ) -> LegalDocument | None: ...

    async def list_for_kind(
        self, kind: LegalDocumentKind
    ) -> list[LegalDocument]: ...


class ConsentRepository(Protocol):
    """Журнал согласий на обработку персональных данных (append-only)."""

    async def add(self, record: ConsentRecord) -> ConsentRecord: ...

    async def list_for_user(self, user_id: int) -> list[ConsentRecord]: ...


class RoleRepository(Protocol):
    """Управление ролями пользователей (many-to-many)."""

    async def assign(self, user_id: int, role: RoleName) -> None: ...

    async def revoke(self, user_id: int, role: RoleName) -> None: ...

    async def roles_of(self, user_id: int) -> set[RoleName]: ...

    async def users_with_role(self, role: RoleName) -> list[User]: ...


class TariffRepository(Protocol):
    """История тарифов."""

    async def active_for(
        self, kind: TariffKind, on_date: date
    ) -> Tariff | None: ...

    async def add(self, tariff: Tariff) -> Tariff: ...


class ScheduleRepository(Protocol):
    """Недельный шаблон расписания."""

    async def active_slots(self) -> list[ScheduleSlot]: ...

    async def add(self, slot: ScheduleSlot) -> ScheduleSlot: ...


class SubscriptionRepository(Protocol):
    """Подписки на месяц и оплаты по ним."""

    async def get_for_month(
        self, period: MonthPeriod
    ) -> Subscription | None: ...

    async def create(self, subscription: Subscription) -> Subscription: ...

    async def update(self, subscription: Subscription) -> None: ...

    async def add_payment(
        self, payment: SubscriptionPayment
    ) -> SubscriptionPayment: ...

    async def payments_of(
        self, subscription_id: int
    ) -> list[SubscriptionPayment]: ...

    async def get_payment(
        self, subscription_id: int, user_id: int
    ) -> SubscriptionPayment | None: ...

    async def update_payment(self, payment: SubscriptionPayment) -> None: ...

    async def delete_payment(self, payment_id: int) -> None: ...


class OneTimeRepository(Protocol):
    """Разовые посещения (тариф хранится в ``TariffRepository``)."""

    async def add_visit(self, visit: OneTimePayment) -> OneTimePayment: ...

    async def get_visit(self, visit_id: int) -> OneTimePayment | None: ...

    async def update_visit(self, visit: OneTimePayment) -> None: ...

    async def visits_in_month(
        self, period: MonthPeriod
    ) -> list[OneTimePayment]: ...

    async def unpaid_visits_of(self, user_id: int) -> list[OneTimePayment]: ...

    async def delete_visit(self, visit_id: int) -> None: ...


class CalendarRepository(Protocol):
    """События календаря."""

    async def add(self, event: CalendarEvent) -> CalendarEvent: ...

    async def get(self, event_id: int) -> CalendarEvent | None: ...

    async def update(self, event: CalendarEvent) -> None: ...

    async def delete(self, event_id: int) -> None: ...

    async def list_for_month(
        self, period: MonthPeriod
    ) -> list[CalendarEvent]: ...


class ActionLogRepository(Protocol):
    """Журнал административных действий."""

    async def add(self, entry: ActionLogEntry) -> ActionLogEntry: ...

    async def recent(self, limit: int = 50) -> list[ActionLogEntry]: ...
