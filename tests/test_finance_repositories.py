"""Тесты хранения финансового учёта: расходы, передачи, корректировки."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from avrora_bot.domain.entities import (
    AccountTransfer,
    BalanceAdjustment,
    Expense,
    OneTimePayment,
    Subscription,
    SubscriptionPayment,
    User,
)
from avrora_bot.domain.enums import ExpenseCategory, PaymentStatus, UserStatus
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.value_objects import MonthPeriod

ADMIN_VK_ID = 1
SEPTEMBER = MonthPeriod(2026, 9)


async def _add_users(
    uow_factory: Callable[[], UnitOfWork], count: int
) -> list[int]:
    async with uow_factory() as uow:
        ids = []
        for n in range(count):
            user = await uow.users.add(
                User(
                    vk_id=200 + n,
                    full_name=f'User {n}',
                    status=UserStatus.ACTIVE,
                )
            )
            ids.append(user.id)
        await uow.commit()
        return ids


def _expense(account: int, spent_on: date, amount: str) -> Expense:
    return Expense(
        spent_on=spent_on,
        category=ExpenseCategory.COACH,
        description='Оплата тренер Елена',
        amount=Decimal(amount),
        account_user_id=account,
        created_by_vk_id=ADMIN_VK_ID,
    )


@pytest.mark.asyncio
async def test_expense_crud_and_listing(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    (sedova,) = await _add_users(uow_factory, 1)
    async with uow_factory() as uow:
        aug = await uow.expenses.add(_expense(sedova, date(2026, 8, 30), '100'))
        sep = await uow.expenses.add(_expense(sedova, date(2026, 9, 5), '3000'))
        await uow.expenses.add(_expense(sedova, date(2026, 10, 1), '500'))
        await uow.commit()
    assert sep.id is not None
    assert sep.created_at is not None

    async with uow_factory() as uow:
        month = await uow.expenses.list_for_month(SEPTEMBER)
        assert [x.id for x in month] == [sep.id]
        until = await uow.expenses.list_until(date(2026, 9, 30))
        assert [x.id for x in until] == [aug.id, sep.id]

        sep.amount = Decimal('4500')
        sep.category = ExpenseCategory.OTHER
        sep.note = 'за две тренировки'
        await uow.expenses.update(sep)
        await uow.expenses.delete(aug.id)
        await uow.commit()

    async with uow_factory() as uow:
        stored = await uow.expenses.get(sep.id)
        assert stored is not None
        assert stored.amount == Decimal('4500')
        assert stored.category is ExpenseCategory.OTHER
        assert stored.note == 'за две тренировки'
        assert await uow.expenses.get(aug.id) is None


@pytest.mark.asyncio
async def test_expense_amount_must_be_positive(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    (sedova,) = await _add_users(uow_factory, 1)
    async with uow_factory() as uow:
        with pytest.raises(IntegrityError):
            await uow.expenses.add(_expense(sedova, date(2026, 9, 1), '0'))


@pytest.mark.asyncio
async def test_transfers_and_adjustments(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    teplova, sedova = await _add_users(uow_factory, 2)
    async with uow_factory() as uow:
        transfer = await uow.transfers.add(
            AccountTransfer(
                transferred_on=date(2026, 9, 10),
                from_user_id=teplova,
                to_user_id=sedova,
                amount=Decimal('1500'),
                created_by_vk_id=ADMIN_VK_ID,
                note='на оплату тренера',
            )
        )
        adjustment = await uow.balance_adjustments.add(
            BalanceAdjustment(
                adjusted_on=date(2026, 8, 19),
                user_id=sedova,
                amount=Decimal('-200'),
                reason='расхождение с наличными',
                created_by_vk_id=ADMIN_VK_ID,
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        assert [
            t.id for t in await uow.transfers.list_for_month(SEPTEMBER)
        ] == [transfer.id]
        assert await uow.transfers.list_until(date(2026, 9, 9)) == []
        stored = await uow.balance_adjustments.list_until(date(2026, 9, 1))
        assert [(a.id, a.amount) for a in stored] == [
            (adjustment.id, Decimal('-200'))
        ]
        await uow.transfers.delete(transfer.id)
        await uow.balance_adjustments.delete(adjustment.id)
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.transfers.get(transfer.id) is None
        assert await uow.balance_adjustments.get(adjustment.id) is None


@pytest.mark.asyncio
async def test_transfer_to_self_is_rejected(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    (sedova,) = await _add_users(uow_factory, 1)
    async with uow_factory() as uow:
        with pytest.raises(IntegrityError):
            await uow.transfers.add(
                AccountTransfer(
                    transferred_on=date(2026, 9, 10),
                    from_user_id=sedova,
                    to_user_id=sedova,
                    amount=Decimal('100'),
                    created_by_vk_id=ADMIN_VK_ID,
                )
            )


@pytest.mark.asyncio
async def test_paid_until_filters_by_status_and_marked_at(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    a, b, c = await _add_users(uow_factory, 3)
    early = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    late = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    async with uow_factory() as uow:
        sub = await uow.subscriptions.create(
            Subscription(
                period_year=2026,
                period_month=9,
                total_amount=Decimal('65750'),
                voters_count=3,
                per_person_amount=Decimal('2450'),
            )
        )
        for user_id, status, marked_at in [
            (a, PaymentStatus.PAID, early),
            (b, PaymentStatus.PAID, late),
            (c, PaymentStatus.UNPAID, None),
        ]:
            await uow.subscriptions.add_payment(
                SubscriptionPayment(
                    subscription_id=sub.id,
                    user_id=user_id,
                    status=status,
                    marked_at=marked_at,
                    collector_vk_id=200,
                )
            )
            await uow.one_time.add_visit(
                OneTimePayment(
                    user_id=user_id,
                    visit_date=date(2026, 9, 1),
                    amount=Decimal('350'),
                    status=status,
                    marked_at=marked_at,
                    collector_vk_id=200,
                )
            )
        await uow.commit()

    cutoff = datetime(2026, 9, 10, tzinfo=UTC)
    async with uow_factory() as uow:
        payments = await uow.subscriptions.paid_payments_until(cutoff)
        assert [p.user_id for p in payments] == [a]
        visits = await uow.one_time.paid_visits_until(cutoff)
        assert [v.user_id for v in visits] == [a]
        assert await uow.subscriptions.get(sub.id) is not None


@pytest.mark.asyncio
async def test_subscription_payment_fact_amount_and_note(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    (user_id,) = await _add_users(uow_factory, 1)
    async with uow_factory() as uow:
        sub = await uow.subscriptions.create(
            Subscription(
                period_year=2026,
                period_month=9,
                total_amount=Decimal('65750'),
                voters_count=1,
                per_person_amount=Decimal('2436'),
                per_percent_amount_fact=Decimal('2450'),
            )
        )
        payment = await uow.subscriptions.add_payment(
            SubscriptionPayment(subscription_id=sub.id, user_id=user_id)
        )
        assert payment.amount is None
        assert payment.paid_amount(sub) == Decimal('2450')

        payment.amount = Decimal('2100')
        payment.note = '350 у Оли Тепловой (зачтена разовая)'
        await uow.subscriptions.update_payment(payment)
        await uow.commit()

    async with uow_factory() as uow:
        stored = await uow.subscriptions.get_payment(sub.id, user_id)
        assert stored is not None
        assert stored.amount == Decimal('2100')
        assert stored.note == '350 у Оли Тепловой (зачтена разовая)'
        assert stored.paid_amount(sub) == Decimal('2100')
