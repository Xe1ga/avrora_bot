"""SQLAlchemy-реализации портов репозиториев.

Каждый репозиторий работает в рамках переданной ``AsyncSession`` (границей
транзакции управляет Unit of Work). Мапперы преобразуют ORM-модели в чистые
доменные сущности и обратно.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from avrora_bot.adapters.database import models as m
from avrora_bot.domain import entities as e
from avrora_bot.domain.enums import (
    EventType,
    PaymentStatus,
    RoleName,
    TariffKind,
    UserStatus,
    Weekday,
)
from avrora_bot.domain.value_objects import MonthPeriod

# ─────────────────────────── мапперы ORM → domain ──────────────────────────


def _user_to_domain(row: m.User) -> e.User:
    return e.User(
        id=row.id,
        vk_id=row.vk_id,
        full_name=row.full_name,
        status=UserStatus(row.status),
        birthdate=row.birthdate,
        height_cm=row.height_cm,
        phone=row.phone,
        created_at=row.created_at,
        roles={RoleName(link.role) for link in row.role_links},
    )


def _tariff_to_domain(row: m.Tariff) -> e.Tariff:
    return e.Tariff(
        id=row.id,
        kind=TariffKind(row.kind),
        amount=row.amount,
        valid_from=row.valid_from,
    )


def _slot_to_domain(row: m.ScheduleTemplate) -> e.ScheduleSlot:
    return e.ScheduleSlot(
        id=row.id,
        weekday=Weekday(row.weekday),
        start=row.start_time,
        end=row.end_time,
        active=row.active,
    )


def _subscription_to_domain(row: m.Subscription) -> e.Subscription:
    return e.Subscription(
        id=row.id,
        period_year=row.period_year,
        period_month=row.period_month,
        total_amount=row.total_amount,
        voters_count=row.voters_count,
        per_person_amount=row.per_person_amount,
        created_at=row.created_at,
    )


def _sub_payment_to_domain(
    row: m.SubscriptionPayment,
) -> e.SubscriptionPayment:
    return e.SubscriptionPayment(
        id=row.id,
        subscription_id=row.subscription_id,
        user_id=row.user_id,
        status=PaymentStatus(row.status),
        marked_at=row.marked_at,
        marked_by_vk_id=row.marked_by_vk_id,
    )


def _one_time_to_domain(row: m.OneTimePayment) -> e.OneTimePayment:
    return e.OneTimePayment(
        id=row.id,
        user_id=row.user_id,
        visit_date=row.visit_date,
        amount=row.amount,
        status=PaymentStatus(row.status),
        marked_at=row.marked_at,
        marked_by_vk_id=row.marked_by_vk_id,
    )


def _event_to_domain(row: m.CalendarEvent) -> e.CalendarEvent:
    return e.CalendarEvent(
        id=row.id,
        event_date=row.event_date,
        event_time=row.event_time,
        event_type=EventType(row.event_type),
        place=row.place,
        comment=row.comment,
        author_vk_id=row.author_vk_id,
    )


def _action_to_domain(row: m.ActionLog) -> e.ActionLogEntry:
    return e.ActionLogEntry(
        id=row.id,
        actor_vk_id=row.actor_vk_id,
        action=row.action,
        details=row.details,
        created_at=row.created_at,
    )


# ─────────────────────────────── репозитории ───────────────────────────────


class SqlUserRepository:
    """Репозиторий пользователей."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_by_vk_id(self, vk_id: int) -> e.User | None:
        row = await self._s.scalar(
            select(m.User)
            .options(selectinload(m.User.role_links))
            .where(m.User.vk_id == vk_id)
        )
        return _user_to_domain(row) if row else None

    async def get_by_id(self, user_id: int) -> e.User | None:
        row = await self._s.get(
            m.User, user_id, options=[selectinload(m.User.role_links)]
        )
        return _user_to_domain(row) if row else None

    async def add(self, user: e.User) -> e.User:
        row = m.User(
            vk_id=user.vk_id,
            full_name=user.full_name,
            status=user.status,
            birthdate=user.birthdate,
            height_cm=user.height_cm,
            phone=user.phone,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row, attribute_names=['role_links'])
        return _user_to_domain(row)

    async def update(self, user: e.User) -> None:
        row = await self._s.get(m.User, user.id)
        if row is None:
            return
        row.full_name = user.full_name
        row.status = user.status
        row.birthdate = user.birthdate
        row.height_cm = user.height_cm
        row.phone = user.phone
        await self._s.flush()

    async def list_by_status(self, status: UserStatus) -> list[e.User]:
        rows = await self._s.scalars(
            select(m.User)
            .options(selectinload(m.User.role_links))
            .where(m.User.status == status)
            .order_by(m.User.id)
        )
        return [_user_to_domain(r) for r in rows]

    async def list_all(self) -> list[e.User]:
        rows = await self._s.scalars(
            select(m.User)
            .options(selectinload(m.User.role_links))
            .order_by(m.User.id)
        )
        return [_user_to_domain(r) for r in rows]


class SqlRoleRepository:
    """Репозиторий ролей."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def assign(self, user_id: int, role: RoleName) -> None:
        exists = await self._s.scalar(
            select(m.UserRole).where(
                m.UserRole.user_id == user_id, m.UserRole.role == role
            )
        )
        if exists is None:
            self._s.add(m.UserRole(user_id=user_id, role=role))
            await self._s.flush()

    async def revoke(self, user_id: int, role: RoleName) -> None:
        row = await self._s.scalar(
            select(m.UserRole).where(
                m.UserRole.user_id == user_id, m.UserRole.role == role
            )
        )
        if row is not None:
            await self._s.delete(row)
            await self._s.flush()

    async def roles_of(self, user_id: int) -> set[RoleName]:
        rows = await self._s.scalars(
            select(m.UserRole.role).where(m.UserRole.user_id == user_id)
        )
        return {RoleName(r) for r in rows}

    async def users_with_role(self, role: RoleName) -> list[e.User]:
        rows = await self._s.scalars(
            select(m.User)
            .options(selectinload(m.User.role_links))
            .join(m.UserRole, m.UserRole.user_id == m.User.id)
            .where(m.UserRole.role == role)
            .order_by(m.User.id)
        )
        return [_user_to_domain(r) for r in rows.unique()]


class SqlTariffRepository:
    """Репозиторий тарифов."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def active_for(
        self, kind: TariffKind, on_date: date
    ) -> e.Tariff | None:
        row = await self._s.scalar(
            select(m.Tariff)
            .where(m.Tariff.kind == kind, m.Tariff.valid_from <= on_date)
            .order_by(m.Tariff.valid_from.desc())
            .limit(1)
        )
        return _tariff_to_domain(row) if row else None

    async def add(self, tariff: e.Tariff) -> e.Tariff:
        row = m.Tariff(
            kind=tariff.kind,
            amount=tariff.amount,
            valid_from=tariff.valid_from,
        )
        self._s.add(row)
        await self._s.flush()
        return _tariff_to_domain(row)


class SqlScheduleRepository:
    """Репозиторий недельного расписания."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def active_slots(self) -> list[e.ScheduleSlot]:
        rows = await self._s.scalars(
            select(m.ScheduleTemplate).where(
                m.ScheduleTemplate.active.is_(True)
            )
        )
        return [_slot_to_domain(r) for r in rows]

    async def add(self, slot: e.ScheduleSlot) -> e.ScheduleSlot:
        row = m.ScheduleTemplate(
            weekday=slot.weekday,
            start_time=slot.start,
            end_time=slot.end,
            active=slot.active,
        )
        self._s.add(row)
        await self._s.flush()
        return _slot_to_domain(row)


class SqlSubscriptionRepository:
    """Репозиторий подписок и оплат."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_for_month(self, period: MonthPeriod) -> e.Subscription | None:
        row = await self._s.scalar(
            select(m.Subscription).where(
                m.Subscription.period_year == period.year,
                m.Subscription.period_month == period.month,
            )
        )
        return _subscription_to_domain(row) if row else None

    async def create(self, subscription: e.Subscription) -> e.Subscription:
        row = m.Subscription(
            period_year=subscription.period_year,
            period_month=subscription.period_month,
            total_amount=subscription.total_amount,
            voters_count=subscription.voters_count,
            per_person_amount=subscription.per_person_amount,
        )
        self._s.add(row)
        await self._s.flush()
        return _subscription_to_domain(row)

    async def update(self, subscription: e.Subscription) -> None:
        row = await self._s.get(m.Subscription, subscription.id)
        if row is None:
            return
        row.total_amount = subscription.total_amount
        row.voters_count = subscription.voters_count
        row.per_person_amount = subscription.per_person_amount
        await self._s.flush()

    async def add_payment(
        self, payment: e.SubscriptionPayment
    ) -> e.SubscriptionPayment:
        row = m.SubscriptionPayment(
            subscription_id=payment.subscription_id,
            user_id=payment.user_id,
            status=payment.status,
            marked_at=payment.marked_at,
            marked_by_vk_id=payment.marked_by_vk_id,
        )
        self._s.add(row)
        await self._s.flush()
        return _sub_payment_to_domain(row)

    async def payments_of(
        self, subscription_id: int
    ) -> list[e.SubscriptionPayment]:
        rows = await self._s.scalars(
            select(m.SubscriptionPayment)
            .where(m.SubscriptionPayment.subscription_id == subscription_id)
            .order_by(m.SubscriptionPayment.id)
        )
        return [_sub_payment_to_domain(r) for r in rows]

    async def get_payment(
        self, subscription_id: int, user_id: int
    ) -> e.SubscriptionPayment | None:
        row = await self._s.scalar(
            select(m.SubscriptionPayment).where(
                m.SubscriptionPayment.subscription_id == subscription_id,
                m.SubscriptionPayment.user_id == user_id,
            )
        )
        return _sub_payment_to_domain(row) if row else None

    async def update_payment(self, payment: e.SubscriptionPayment) -> None:
        row = await self._s.get(m.SubscriptionPayment, payment.id)
        if row is None:
            return
        row.status = payment.status
        row.marked_at = payment.marked_at
        row.marked_by_vk_id = payment.marked_by_vk_id
        await self._s.flush()


class SqlOneTimeRepository:
    """Репозиторий разовых посещений."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add_visit(self, visit: e.OneTimePayment) -> e.OneTimePayment:
        row = m.OneTimePayment(
            user_id=visit.user_id,
            visit_date=visit.visit_date,
            amount=visit.amount,
            status=visit.status,
            marked_at=visit.marked_at,
            marked_by_vk_id=visit.marked_by_vk_id,
        )
        self._s.add(row)
        await self._s.flush()
        return _one_time_to_domain(row)

    async def get_visit(self, visit_id: int) -> e.OneTimePayment | None:
        row = await self._s.get(m.OneTimePayment, visit_id)
        return _one_time_to_domain(row) if row else None

    async def update_visit(self, visit: e.OneTimePayment) -> None:
        row = await self._s.get(m.OneTimePayment, visit.id)
        if row is None:
            return
        row.status = visit.status
        row.amount = visit.amount
        row.marked_at = visit.marked_at
        row.marked_by_vk_id = visit.marked_by_vk_id
        await self._s.flush()

    async def visits_in_month(
        self, period: MonthPeriod
    ) -> list[e.OneTimePayment]:
        rows = await self._s.scalars(
            select(m.OneTimePayment)
            .where(
                m.OneTimePayment.visit_date >= period.first_day,
                m.OneTimePayment.visit_date <= period.last_day,
            )
            .order_by(m.OneTimePayment.visit_date)
        )
        return [_one_time_to_domain(r) for r in rows]


class SqlCalendarRepository:
    """Репозиторий событий календаря."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, event: e.CalendarEvent) -> e.CalendarEvent:
        row = m.CalendarEvent(
            event_date=event.event_date,
            event_time=event.event_time,
            event_type=event.event_type,
            place=event.place,
            comment=event.comment,
            author_vk_id=event.author_vk_id,
        )
        self._s.add(row)
        await self._s.flush()
        return _event_to_domain(row)

    async def get(self, event_id: int) -> e.CalendarEvent | None:
        row = await self._s.get(m.CalendarEvent, event_id)
        return _event_to_domain(row) if row else None

    async def update(self, event: e.CalendarEvent) -> None:
        row = await self._s.get(m.CalendarEvent, event.id)
        if row is None:
            return
        row.event_date = event.event_date
        row.event_time = event.event_time
        row.event_type = event.event_type
        row.place = event.place
        row.comment = event.comment
        await self._s.flush()

    async def delete(self, event_id: int) -> None:
        row = await self._s.get(m.CalendarEvent, event_id)
        if row is not None:
            await self._s.delete(row)
            await self._s.flush()

    async def list_for_month(
        self, period: MonthPeriod
    ) -> list[e.CalendarEvent]:
        rows = await self._s.scalars(
            select(m.CalendarEvent)
            .where(
                m.CalendarEvent.event_date >= period.first_day,
                m.CalendarEvent.event_date <= period.last_day,
            )
            .order_by(m.CalendarEvent.event_date, m.CalendarEvent.event_time)
        )
        return [_event_to_domain(r) for r in rows]


class SqlActionLogRepository:
    """Репозиторий журнала действий."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, entry: e.ActionLogEntry) -> e.ActionLogEntry:
        row = m.ActionLog(
            actor_vk_id=entry.actor_vk_id,
            action=entry.action,
            details=entry.details,
        )
        self._s.add(row)
        await self._s.flush()
        return _action_to_domain(row)

    async def recent(self, limit: int = 50) -> list[e.ActionLogEntry]:
        rows = await self._s.scalars(
            select(m.ActionLog).order_by(m.ActionLog.id.desc()).limit(limit)
        )
        return [_action_to_domain(r) for r in rows]
