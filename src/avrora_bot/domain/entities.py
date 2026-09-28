"""Доменные сущности (чистые dataclass-модели, без привязки к ORM).

Сущности представляют бизнес-объекты и передаются между слоями. Слой БД
(adapters/database) отображает их на ORM-модели SQLAlchemy.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from avrora_bot.domain.enums import (
    EventStatus,
    EventType,
    ExpenseCategory,
    LegalDocumentKind,
    PaymentStatus,
    RoleName,
    TariffKind,
    UserStatus,
    Weekday,
)


@dataclass(slots=True)
class User:
    """Пользователь клуба.

    ``vk_id`` может быть ``None`` — для игрока, добавленного вручную без
    аккаунта ВК (см. ``RegistrationUseCases.admin_add_player_without_vk``).
    Такой профиль ведёт учёт (абонементы/разовые посещения) так же, как
    обычный: остальной код находит его по ФИО через
    ``application.services.user_lookup.resolve_user``, а не по vk_id.
    """

    vk_id: int | None
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
class LegalDocument:
    """Версия опубликованного юридического документа (``docs/legal/``).

    Одна запись — один текст: версия и дата из заголовка страницы, ссылка
    на публикацию, sha256 файла и сам HTML на момент фиксации. Записи
    неизменяемы: правка текста означает новую версию и новую запись, а
    старые остаются доказательством того, с каким именно текстом
    соглашались пользователи (см. ``ConsentRecord``).
    """

    kind: LegalDocumentKind
    version: str
    sha256: str
    content: str
    effective_date: date | None = None
    url: str | None = None
    created_at: datetime | None = None
    id: int | None = None


@dataclass(slots=True)
class ConsentRecord:
    """Факт согласия пользователя на обработку персональных данных.

    Append-only: одна запись — один факт согласия с конкретными версиями
    документов. Хранятся не строки-версии, а ссылки на ``LegalDocument``,
    где лежит полный текст согласия и политики, с которыми пользователь
    ознакомился (см. ``adapters.database.models.UserConsent``).
    """

    user_id: int
    consent_document_id: int
    privacy_policy_document_id: int
    given_at: datetime | None = None
    id: int | None = None


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
    place: str | None = None

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
    per_person_amount: Decimal  # расчётная сумма на человека
    per_percent_amount_fact: Decimal | None = None  # факт. сумма сборщика
    id: int | None = None
    created_at: datetime | None = None

    @property
    def effective_amount(self) -> Decimal:
        """Сумма, которая по факту собирается с участников (ТЗ 3.2).

        Приоритет — фактическая сумма сборщика, если она зафиксирована;
        иначе расчётная сумма.
        """
        return (
            self.per_percent_amount_fact
            if self.per_percent_amount_fact is not None
            else self.per_person_amount
        )


@dataclass(slots=True)
class SubscriptionPayment:
    """Строка оплаты абонемента для конкретного участника."""

    subscription_id: int
    user_id: int
    status: PaymentStatus = PaymentStatus.UNPAID
    marked_at: datetime | None = None
    # vk_id сборщика, который фактически собрал оплату (не всегда тот же,
    # кто её отметил в боте — см. OneTimeUseCases.set_visit_collector).
    collector_vk_id: int | None = None
    # Фактически внесённая сумма, если она отличается от суммы абонемента
    # (например, часть абонемента зачтена разовым посещением); ``None`` —
    # внесена ровно ``Subscription.effective_amount``.
    amount: Decimal | None = None
    # Свободное примечание сборщика (колонка «Примечание» отчёта) —
    # пояснение к нестандартной сумме и т. п.
    note: str | None = None
    id: int | None = None

    def paid_amount(self, subscription: Subscription) -> Decimal:
        """Сумма, которую участник вносит по этой строке оплаты."""
        return (
            self.amount
            if self.amount is not None
            else subscription.effective_amount
        )


@dataclass(slots=True)
class OneTimePayment:
    """Разовое посещение."""

    user_id: int
    visit_date: date
    amount: Decimal
    status: PaymentStatus = PaymentStatus.UNPAID
    marked_at: datetime | None = None
    # vk_id сборщика, который фактически собрал оплату (не всегда тот же,
    # кто её отметил в боте — см. OneTimeUseCases.set_visit_collector).
    collector_vk_id: int | None = None
    # Свободное примечание сборщика (колонка «Примечание» отчёта).
    note: str | None = None
    id: int | None = None


@dataclass(slots=True)
class Expense:
    """Расход клубных денег со счёта конкретного человека.

    «Счёт» — это человек, у которого на руках деньги клуба (сборщик или
    бывший сборщик), а не банковский счёт: ``account_user_id`` — с чьих
    денег оплачено.
    """

    spent_on: date
    category: ExpenseCategory
    description: str  # «Оплата тренер Елена», «Оплата зала сентябрь»
    amount: Decimal  # всегда > 0
    account_user_id: int
    created_by_vk_id: int
    note: str | None = None
    id: int | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class AccountTransfer:
    """Передача клубных денег от одного человека другому."""

    transferred_on: date
    from_user_id: int
    to_user_id: int
    amount: Decimal  # всегда > 0
    created_by_vk_id: int
    note: str | None = None
    id: int | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class BalanceAdjustment:
    """Ручная корректировка остатка на счёте (вносит администратор).

    Начальный остаток на дату запуска учёта (деньги, собранные до бота)
    или исправление расхождения с реальными деньгами на руках. Сумма со
    знаком: «+» — добавить, «−» — списать.
    """

    adjusted_on: date
    user_id: int
    amount: Decimal  # != 0
    reason: str
    created_by_vk_id: int
    id: int | None = None
    created_at: datetime | None = None


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
    status: EventStatus = EventStatus.PLANNED


@dataclass(slots=True)
class ActionLogEntry:
    """Запись журнала административных действий."""

    actor_vk_id: int
    action: str
    details: str | None = None
    created_at: datetime | None = None
    id: int | None = None
