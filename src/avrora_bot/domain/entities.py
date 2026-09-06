"""Доменные сущности (чистые dataclass-модели, без привязки к ORM).

Сущности представляют бизнес-объекты и передаются между слоями. Слой БД
(adapters/database) отображает их на ORM-модели SQLAlchemy.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from avrora_bot.domain.enums import (
    EventType,
    PaymentStatus,
    RoleName,
    TariffKind,
    UserStatus,
    Weekday,
)


@dataclass(slots=True)
class User:
    """Пользователь клуба."""

    vk_id: int
    full_name: str
    status: UserStatus = UserStatus.PENDING
    birthdate: date | None = None
    height_cm: int | None = None
    phone: str | None = None
    id: int | None = None
    created_at: datetime | None = None
    roles: set[RoleName] = field(default_factory=set)

    def has_role(self, role: RoleName) -> bool:
        """Проверяет наличие роли у пользователя."""
        return role in self.roles


@dataclass(slots=True)
class Tariff:
    """Значение тарифа с датой начала действия (ведётся история)."""

    kind: TariffKind
    amount: Decimal
    valid_from: date
    id: int | None = None


@dataclass(slots=True)
class ScheduleSlot:
    """Слот недельного расписания тренировок.

    Одна запись = одна тренировка в конкретный день недели с временным
    диапазоном. Используется для авторасчёта числа тренировок и часов зала.
    """

    weekday: Weekday
    start: time
    end: time
    id: int | None = None
    active: bool = True

    @property
    def hall_hours(self) -> Decimal:
        """Длительность слота в часах (для расчёта стоимости зала)."""
        start_min = self.start.hour * 60 + self.start.minute
        end_min = self.end.hour * 60 + self.end.minute
        return Decimal(end_min - start_min) / Decimal(60)


@dataclass(slots=True)
class Subscription:
    """Подписка (абонемент) на месяц."""

    period_year: int
    period_month: int
    total_amount: Decimal  # общая сумма сбора за месяц
    voters_count: int  # число проголосовавших
    per_person_amount: Decimal  # сумма на человека (расчёт/override)
    id: int | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class SubscriptionPayment:
    """Строка оплаты абонемента для конкретного участника."""

    subscription_id: int
    user_id: int
    status: PaymentStatus = PaymentStatus.UNPAID
    marked_at: datetime | None = None
    marked_by_vk_id: int | None = None
    id: int | None = None


@dataclass(slots=True)
class OneTimePayment:
    """Разовое посещение."""

    user_id: int
    visit_date: date
    amount: Decimal
    status: PaymentStatus = PaymentStatus.UNPAID
    marked_at: datetime | None = None
    marked_by_vk_id: int | None = None
    id: int | None = None


@dataclass(slots=True)
class CalendarEvent:
    """Событие календаря — тренировка или игра."""

    event_date: date
    event_time: time | None
    event_type: EventType
    place: str | None
    comment: str | None
    author_vk_id: int
    id: int | None = None


@dataclass(slots=True)
class ActionLogEntry:
    """Запись журнала административных действий."""

    actor_vk_id: int
    action: str
    details: str | None = None
    created_at: datetime | None = None
    id: int | None = None
