"""Доменные сущности (чистые dataclass-модели, без привязки к ORM).

Сущности представляют бизнес-объекты и передаются между слоями. Слой БД
(adapters/database) отображает их на ORM-модели SQLAlchemy.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from avrora_bot.domain.enums import (
    EventType,
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
