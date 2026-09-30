"""SQLAlchemy-реализации портов репозиториев.

Каждый репозиторий работает в рамках переданной ``AsyncSession`` (границей
транзакции управляет Unit of Work). Мапперы преобразуют ORM-модели в чистые
доменные сущности и обратно.
"""

from datetime import date, datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from avrora_bot.adapters.database import models as m
from avrora_bot.adapters.database.crypto import PiiCipher
from avrora_bot.domain import entities as e
from avrora_bot.domain.enums import (
    BirthdayReminderKind,
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
from avrora_bot.domain.value_objects import MonthPeriod

# ─────────────────────────── мапперы ORM → domain ──────────────────────────


# Опции загрузки, применяемые ко всем select/get пользователей, чтобы
# получить ФИО/телефон/ДР/рост без N+1 запросов (одним batch-selectinload
# на каждую связь, независимо от числа пользователей).
_USER_LOAD_OPTIONS = (
    selectinload(m.User.role_links),
    selectinload(m.User.full_name_link),
    selectinload(m.User.phone_link),
    selectinload(m.User.birthdate_link),
    selectinload(m.User.height_link),
)


def _user_to_domain(row: m.User, cipher: PiiCipher) -> e.User:
    full_name = cipher.decrypt_str(row.full_name_link.full_name_enc)
    phone = cipher.decrypt_opt(
        row.phone_link.phone_enc if row.phone_link else None
    )
    return e.User(
        id=row.id,
        vk_id=row.vk_id,
        full_name=full_name,
        status=UserStatus(row.status),
        birthdate=row.birthdate_link.birthdate if row.birthdate_link else None,
        height_cm=row.height_link.height_cm if row.height_link else None,
        phone=phone,
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
        place=row.place,
    )


def _subscription_to_domain(row: m.Subscription) -> e.Subscription:
    return e.Subscription(
        id=row.id,
        period_year=row.period_year,
        period_month=row.period_month,
        total_amount=row.total_amount,
        voters_count=row.voters_count,
        per_person_amount=row.per_person_amount,
        per_percent_amount_fact=row.per_percent_amount_fact,
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
        collector_vk_id=row.collector_vk_id,
        amount=row.amount,
        note=row.note,
    )


def _one_time_to_domain(row: m.OneTimePayment) -> e.OneTimePayment:
    return e.OneTimePayment(
        id=row.id,
        user_id=row.user_id,
        visit_date=row.visit_date,
        amount=row.amount,
        status=PaymentStatus(row.status),
        marked_at=row.marked_at,
        collector_vk_id=row.collector_vk_id,
        note=row.note,
    )


def _expense_to_domain(row: m.Expense) -> e.Expense:
    return e.Expense(
        id=row.id,
        spent_on=row.spent_on,
        category=ExpenseCategory(row.category),
        description=row.description,
        amount=row.amount,
        account_user_id=row.account_user_id,
        created_by_vk_id=row.created_by_vk_id,
        note=row.note,
        created_at=row.created_at,
    )


def _transfer_to_domain(row: m.AccountTransfer) -> e.AccountTransfer:
    return e.AccountTransfer(
        id=row.id,
        transferred_on=row.transferred_on,
        from_user_id=row.from_user_id,
        to_user_id=row.to_user_id,
        amount=row.amount,
        created_by_vk_id=row.created_by_vk_id,
        note=row.note,
        created_at=row.created_at,
    )


def _adjustment_to_domain(row: m.BalanceAdjustment) -> e.BalanceAdjustment:
    return e.BalanceAdjustment(
        id=row.id,
        adjusted_on=row.adjusted_on,
        user_id=row.user_id,
        amount=row.amount,
        reason=row.reason,
        created_by_vk_id=row.created_by_vk_id,
        created_at=row.created_at,
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
        status=EventStatus(row.status),
    )


def _action_to_domain(row: m.ActionLog) -> e.ActionLogEntry:
    return e.ActionLogEntry(
        id=row.id,
        actor_vk_id=row.actor_vk_id,
        action=row.action,
        details=row.details,
        created_at=row.created_at,
    )


def _consent_to_domain(row: m.UserConsent) -> e.ConsentRecord:
    return e.ConsentRecord(
        id=row.id,
        user_id=row.user_id,
        consent_document_id=row.consent_document_id,
        privacy_policy_document_id=row.privacy_policy_document_id,
        given_at=row.given_at,
    )


def _legal_document_to_domain(row: m.LegalDocument) -> e.LegalDocument:
    return e.LegalDocument(
        id=row.id,
        kind=LegalDocumentKind(row.kind),
        version=row.version,
        sha256=row.sha256,
        content=row.content,
        effective_date=row.effective_date,
        url=row.url,
        created_at=row.created_at,
    )


# ─────────────────────────────── репозитории ───────────────────────────────


class SqlUserRepository:
    """Репозиторий пользователей.

    Шифрует/расшифровывает ФИО и телефон на границе с БД (``PiiCipher``);
    остальной код работает с доменной сущностью ``e.User`` как с plaintext.
    """

    def __init__(self, session: AsyncSession, cipher: PiiCipher) -> None:
        self._s = session
        self._cipher = cipher

    async def get_by_vk_id(self, vk_id: int | None) -> e.User | None:
        # ``vk_id IS NULL`` матчит все ручные («безВК») профили сразу —
        # не тот вызов, который должен когда-либо однозначно находить
        # одного человека, поэтому обрываем сразу же, не уходя в SQL.
        if vk_id is None:
            return None
        row = await self._s.scalar(
            select(m.User)
            .options(*_USER_LOAD_OPTIONS)
            .where(m.User.vk_id == vk_id)
        )
        return _user_to_domain(row, self._cipher) if row else None

    async def get_by_id(self, user_id: int) -> e.User | None:
        row = await self._s.get(
            m.User, user_id, options=list(_USER_LOAD_OPTIONS)
        )
        return _user_to_domain(row, self._cipher) if row else None

    async def add(self, user: e.User) -> e.User:
        row = m.User(vk_id=user.vk_id, status=user.status)
        row.full_name_link = m.UserFullName(
            full_name_enc=self._cipher.encrypt_str(user.full_name)
        )
        row.phone_link = m.UserPhone(
            phone_enc=self._cipher.encrypt_opt(user.phone)
        )
        row.birthdate_link = m.UserBirthdate(birthdate=user.birthdate)
        row.height_link = m.UserHeight(height_cm=user.height_cm)
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(
            row,
            attribute_names=[
                'role_links',
                'full_name_link',
                'phone_link',
                'birthdate_link',
                'height_link',
            ],
        )
        return _user_to_domain(row, self._cipher)

    async def update(self, user: e.User) -> None:
        row = await self._s.get(
            m.User, user.id, options=list(_USER_LOAD_OPTIONS)
        )
        if row is None:
            return
        row.status = user.status
        row.full_name_link.full_name_enc = self._cipher.encrypt_str(
            user.full_name
        )
        row.phone_link.phone_enc = self._cipher.encrypt_opt(user.phone)
        row.birthdate_link.birthdate = user.birthdate
        row.height_link.height_cm = user.height_cm
        await self._s.flush()

    async def list_by_status(self, status: UserStatus) -> list[e.User]:
        rows = await self._s.scalars(
            select(m.User)
            .options(*_USER_LOAD_OPTIONS)
            .where(m.User.status == status)
            .order_by(m.User.id)
        )
        return [_user_to_domain(r, self._cipher) for r in rows]

    async def list_all(self) -> list[e.User]:
        rows = await self._s.scalars(
            select(m.User).options(*_USER_LOAD_OPTIONS).order_by(m.User.id)
        )
        return [_user_to_domain(r, self._cipher) for r in rows]


class SqlRoleRepository:
    """Репозиторий ролей."""

    def __init__(self, session: AsyncSession, cipher: PiiCipher) -> None:
        self._s = session
        self._cipher = cipher

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
            .options(*_USER_LOAD_OPTIONS)
            .join(m.UserRole, m.UserRole.user_id == m.User.id)
            .where(m.UserRole.role == role)
            .order_by(m.User.id)
        )
        return [_user_to_domain(r, self._cipher) for r in rows.unique()]


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
            place=slot.place,
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
            per_percent_amount_fact=subscription.per_percent_amount_fact,
        )
        self._s.add(row)
        await self._s.flush()
        return _subscription_to_domain(row)

    async def get(self, subscription_id: int) -> e.Subscription | None:
        row = await self._s.get(m.Subscription, subscription_id)
        return _subscription_to_domain(row) if row else None

    async def update(self, subscription: e.Subscription) -> None:
        row = await self._s.get(m.Subscription, subscription.id)
        if row is None:
            return
        row.total_amount = subscription.total_amount
        row.voters_count = subscription.voters_count
        row.per_person_amount = subscription.per_person_amount
        row.per_percent_amount_fact = subscription.per_percent_amount_fact
        await self._s.flush()

    async def add_payment(
        self, payment: e.SubscriptionPayment
    ) -> e.SubscriptionPayment:
        row = m.SubscriptionPayment(
            subscription_id=payment.subscription_id,
            user_id=payment.user_id,
            status=payment.status,
            marked_at=payment.marked_at,
            collector_vk_id=payment.collector_vk_id,
            amount=payment.amount,
            note=payment.note,
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
        row.collector_vk_id = payment.collector_vk_id
        row.amount = payment.amount
        row.note = payment.note
        await self._s.flush()

    async def delete_payment(self, payment_id: int) -> None:
        row = await self._s.get(m.SubscriptionPayment, payment_id)
        if row is not None:
            await self._s.delete(row)
            await self._s.flush()

    async def paid_payments_until(
        self, until: datetime
    ) -> list[e.SubscriptionPayment]:
        rows = await self._s.scalars(
            select(m.SubscriptionPayment)
            .where(
                m.SubscriptionPayment.status == PaymentStatus.PAID,
                m.SubscriptionPayment.marked_at <= until,
            )
            .order_by(m.SubscriptionPayment.marked_at)
        )
        return [_sub_payment_to_domain(r) for r in rows]


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
            collector_vk_id=visit.collector_vk_id,
            note=visit.note,
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
        row.visit_date = visit.visit_date
        row.status = visit.status
        row.amount = visit.amount
        row.marked_at = visit.marked_at
        row.collector_vk_id = visit.collector_vk_id
        row.note = visit.note
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

    async def unpaid_visits_of(self, user_id: int) -> list[e.OneTimePayment]:
        rows = await self._s.scalars(
            select(m.OneTimePayment)
            .where(
                m.OneTimePayment.user_id == user_id,
                m.OneTimePayment.status == PaymentStatus.UNPAID,
            )
            .order_by(m.OneTimePayment.visit_date)
        )
        return [_one_time_to_domain(r) for r in rows]

    async def delete_visit(self, visit_id: int) -> None:
        row = await self._s.get(m.OneTimePayment, visit_id)
        if row is not None:
            await self._s.delete(row)
            await self._s.flush()

    async def paid_visits_until(
        self, until: datetime
    ) -> list[e.OneTimePayment]:
        rows = await self._s.scalars(
            select(m.OneTimePayment)
            .where(
                m.OneTimePayment.status == PaymentStatus.PAID,
                m.OneTimePayment.marked_at <= until,
            )
            .order_by(m.OneTimePayment.marked_at)
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
            status=event.status,
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
        row.status = event.status
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

    async def list_planned_until(self, day: date) -> list[e.CalendarEvent]:
        rows = await self._s.scalars(
            select(m.CalendarEvent).where(
                m.CalendarEvent.status == EventStatus.PLANNED,
                m.CalendarEvent.event_date <= day,
            )
        )
        return [_event_to_domain(r) for r in rows]


class SqlExpenseRepository:
    """Репозиторий расходов."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, expense: e.Expense) -> e.Expense:
        row = m.Expense(
            spent_on=expense.spent_on,
            category=expense.category,
            description=expense.description,
            amount=expense.amount,
            account_user_id=expense.account_user_id,
            created_by_vk_id=expense.created_by_vk_id,
            note=expense.note,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _expense_to_domain(row)

    async def get(self, expense_id: int) -> e.Expense | None:
        row = await self._s.get(m.Expense, expense_id)
        return _expense_to_domain(row) if row else None

    async def update(self, expense: e.Expense) -> None:
        row = await self._s.get(m.Expense, expense.id)
        if row is None:
            return
        row.spent_on = expense.spent_on
        row.category = expense.category
        row.description = expense.description
        row.amount = expense.amount
        row.account_user_id = expense.account_user_id
        row.note = expense.note
        await self._s.flush()

    async def delete(self, expense_id: int) -> None:
        row = await self._s.get(m.Expense, expense_id)
        if row is not None:
            await self._s.delete(row)
            await self._s.flush()

    async def list_for_month(self, period: MonthPeriod) -> list[e.Expense]:
        rows = await self._s.scalars(
            select(m.Expense)
            .where(
                m.Expense.spent_on >= period.first_day,
                m.Expense.spent_on <= period.last_day,
            )
            .order_by(m.Expense.spent_on, m.Expense.id)
        )
        return [_expense_to_domain(r) for r in rows]

    async def list_until(self, day: date) -> list[e.Expense]:
        rows = await self._s.scalars(
            select(m.Expense)
            .where(m.Expense.spent_on <= day)
            .order_by(m.Expense.spent_on, m.Expense.id)
        )
        return [_expense_to_domain(r) for r in rows]


class SqlAccountTransferRepository:
    """Репозиторий передач денег между людьми."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, transfer: e.AccountTransfer) -> e.AccountTransfer:
        row = m.AccountTransfer(
            transferred_on=transfer.transferred_on,
            from_user_id=transfer.from_user_id,
            to_user_id=transfer.to_user_id,
            amount=transfer.amount,
            created_by_vk_id=transfer.created_by_vk_id,
            note=transfer.note,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _transfer_to_domain(row)

    async def get(self, transfer_id: int) -> e.AccountTransfer | None:
        row = await self._s.get(m.AccountTransfer, transfer_id)
        return _transfer_to_domain(row) if row else None

    async def delete(self, transfer_id: int) -> None:
        row = await self._s.get(m.AccountTransfer, transfer_id)
        if row is not None:
            await self._s.delete(row)
            await self._s.flush()

    async def list_for_month(
        self, period: MonthPeriod
    ) -> list[e.AccountTransfer]:
        rows = await self._s.scalars(
            select(m.AccountTransfer)
            .where(
                m.AccountTransfer.transferred_on >= period.first_day,
                m.AccountTransfer.transferred_on <= period.last_day,
            )
            .order_by(m.AccountTransfer.transferred_on, m.AccountTransfer.id)
        )
        return [_transfer_to_domain(r) for r in rows]

    async def list_until(self, day: date) -> list[e.AccountTransfer]:
        rows = await self._s.scalars(
            select(m.AccountTransfer)
            .where(m.AccountTransfer.transferred_on <= day)
            .order_by(m.AccountTransfer.transferred_on, m.AccountTransfer.id)
        )
        return [_transfer_to_domain(r) for r in rows]


class SqlBalanceAdjustmentRepository:
    """Репозиторий ручных корректировок остатков."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, adjustment: e.BalanceAdjustment) -> e.BalanceAdjustment:
        row = m.BalanceAdjustment(
            adjusted_on=adjustment.adjusted_on,
            user_id=adjustment.user_id,
            amount=adjustment.amount,
            reason=adjustment.reason,
            created_by_vk_id=adjustment.created_by_vk_id,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _adjustment_to_domain(row)

    async def get(self, adjustment_id: int) -> e.BalanceAdjustment | None:
        row = await self._s.get(m.BalanceAdjustment, adjustment_id)
        return _adjustment_to_domain(row) if row else None

    async def delete(self, adjustment_id: int) -> None:
        row = await self._s.get(m.BalanceAdjustment, adjustment_id)
        if row is not None:
            await self._s.delete(row)
            await self._s.flush()

    async def list_until(self, day: date) -> list[e.BalanceAdjustment]:
        rows = await self._s.scalars(
            select(m.BalanceAdjustment)
            .where(m.BalanceAdjustment.adjusted_on <= day)
            .order_by(m.BalanceAdjustment.adjusted_on, m.BalanceAdjustment.id)
        )
        return [_adjustment_to_domain(r) for r in rows]


class SqlBirthdaySubscriptionRepository:
    """Репозиторий подписок на дни рождения."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, subscriber_user_id: int, target_user_id: int) -> None:
        exists = await self._s.scalar(
            select(m.BirthdaySubscription.id).where(
                m.BirthdaySubscription.subscriber_user_id == subscriber_user_id,
                m.BirthdaySubscription.target_user_id == target_user_id,
            )
        )
        if exists is None:
            self._s.add(
                m.BirthdaySubscription(
                    subscriber_user_id=subscriber_user_id,
                    target_user_id=target_user_id,
                )
            )
            await self._s.flush()

    async def remove(
        self, subscriber_user_id: int, target_user_id: int
    ) -> None:
        await self._s.execute(
            delete(m.BirthdaySubscription).where(
                m.BirthdaySubscription.subscriber_user_id == subscriber_user_id,
                m.BirthdaySubscription.target_user_id == target_user_id,
            )
        )

    async def target_ids_of(self, subscriber_user_id: int) -> set[int]:
        rows = await self._s.scalars(
            select(m.BirthdaySubscription.target_user_id).where(
                m.BirthdaySubscription.subscriber_user_id == subscriber_user_id
            )
        )
        return set(rows)

    async def list_all(self) -> list[e.BirthdaySubscription]:
        rows = await self._s.scalars(
            select(m.BirthdaySubscription).order_by(m.BirthdaySubscription.id)
        )
        return [
            e.BirthdaySubscription(
                id=r.id,
                subscriber_user_id=r.subscriber_user_id,
                target_user_id=r.target_user_id,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def delete_for_user(self, user_id: int) -> None:
        await self._s.execute(
            delete(m.BirthdaySubscription).where(
                or_(
                    m.BirthdaySubscription.subscriber_user_id == user_id,
                    m.BirthdaySubscription.target_user_id == user_id,
                )
            )
        )


class SqlBirthdayReminderRepository:
    """Репозиторий журнала напоминаний о днях рождения."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, reminder: e.BirthdayReminder) -> None:
        self._s.add(
            m.BirthdayReminder(
                subscriber_user_id=reminder.subscriber_user_id,
                target_user_id=reminder.target_user_id,
                kind=reminder.kind,
                occasion=reminder.occasion,
            )
        )
        await self._s.flush()

    async def list_since(self, day: date) -> list[e.BirthdayReminder]:
        rows = await self._s.scalars(
            select(m.BirthdayReminder)
            .where(m.BirthdayReminder.occasion >= day)
            .order_by(m.BirthdayReminder.id)
        )
        return [
            e.BirthdayReminder(
                id=r.id,
                subscriber_user_id=r.subscriber_user_id,
                target_user_id=r.target_user_id,
                kind=BirthdayReminderKind(r.kind),
                occasion=r.occasion,
                sent_at=r.sent_at,
            )
            for r in rows
        ]

    async def delete_for_user(self, user_id: int) -> None:
        await self._s.execute(
            delete(m.BirthdayReminder).where(
                or_(
                    m.BirthdayReminder.subscriber_user_id == user_id,
                    m.BirthdayReminder.target_user_id == user_id,
                )
            )
        )


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


class SqlLegalDocumentRepository:
    """Репозиторий версий юридических документов (``docs/legal/``)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, document: e.LegalDocument) -> e.LegalDocument:
        row = m.LegalDocument(
            kind=document.kind,
            version=document.version,
            effective_date=document.effective_date,
            url=document.url,
            sha256=document.sha256,
            content=document.content,
        )
        self._s.add(row)
        await self._s.flush()
        return _legal_document_to_domain(row)

    async def get(self, document_id: int) -> e.LegalDocument | None:
        row = await self._s.get(m.LegalDocument, document_id)
        return _legal_document_to_domain(row) if row else None

    async def get_by_version(
        self, kind: LegalDocumentKind, version: str
    ) -> e.LegalDocument | None:
        row = await self._s.scalar(
            select(m.LegalDocument).where(
                m.LegalDocument.kind == kind,
                m.LegalDocument.version == version,
            )
        )
        return _legal_document_to_domain(row) if row else None

    async def current(self, kind: LegalDocumentKind) -> e.LegalDocument | None:
        """Возвращает последнюю зарегистрированную версию документа.

        Актуальной считается позднее всех добавленная строка: версии
        регистрируются по мере публикации новых текстов, поэтому порядок
        добавления и есть хронология версий.
        """
        row = await self._s.scalar(
            select(m.LegalDocument)
            .where(m.LegalDocument.kind == kind)
            .order_by(m.LegalDocument.id.desc())
            .limit(1)
        )
        return _legal_document_to_domain(row) if row else None

    async def list_for_kind(
        self, kind: LegalDocumentKind
    ) -> list[e.LegalDocument]:
        rows = await self._s.scalars(
            select(m.LegalDocument)
            .where(m.LegalDocument.kind == kind)
            .order_by(m.LegalDocument.id)
        )
        return [_legal_document_to_domain(r) for r in rows]


class SqlConsentRepository:
    """Репозиторий журнала согласий на обработку персональных данных."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, record: e.ConsentRecord) -> e.ConsentRecord:
        row = m.UserConsent(
            user_id=record.user_id,
            consent_document_id=record.consent_document_id,
            privacy_policy_document_id=record.privacy_policy_document_id,
        )
        self._s.add(row)
        await self._s.flush()
        return _consent_to_domain(row)

    async def list_for_user(self, user_id: int) -> list[e.ConsentRecord]:
        rows = await self._s.scalars(
            select(m.UserConsent)
            .where(m.UserConsent.user_id == user_id)
            .order_by(m.UserConsent.id)
        )
        return [_consent_to_domain(r) for r in rows]
