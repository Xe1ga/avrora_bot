"""Тесты остатков на дату: сборы + расходы + передачи + корректировки."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from avrora_bot.adapters.database.seed import seed_reference_data
from avrora_bot.adapters.vk.handlers.balances import _format_report
from avrora_bot.application.services.clock import ClubClock
from avrora_bot.application.use_cases.balances import BalanceUseCases
from avrora_bot.application.use_cases.finance import FinanceUseCases
from avrora_bot.application.use_cases.one_time import OneTimeUseCases
from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.application.use_cases.subscriptions import SubscriptionUseCases
from avrora_bot.domain.enums import ExpenseCategory, RoleName
from avrora_bot.domain.errors import NotFoundError, PermissionDeniedError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.value_objects import MonthPeriod
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1
SEDOVA_VK_ID = 101
RITA_VK_ID = 102
SVETA_VK_ID = 103  # бывший сборщик: деньги на руках, роли нет
PLAYER_A_VK_ID = 201
PLAYER_B_VK_ID = 202
SEPTEMBER = MonthPeriod(2026, 9)


class _Club:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        vk = FakeVkGateway(admins={ADMIN_VK_ID})
        self.uow_factory = uow_factory
        self.reg = RegistrationUseCases(uow_factory, vk)
        self.roles = RoleUseCases(uow_factory, vk)
        self.subs = SubscriptionUseCases(uow_factory, vk)
        self.one_time = OneTimeUseCases(uow_factory, vk)
        self.finance = FinanceUseCases(uow_factory, vk)
        self.balances = BalanceUseCases(
            uow_factory, vk, ClubClock('Europe/Moscow')
        )

    async def set_up(self) -> None:
        async with self.uow_factory() as uow:
            await seed_reference_data(uow)
            await uow.commit()
        for vk_id, name in [
            (SEDOVA_VK_ID, 'Седова Ольга'),
            (RITA_VK_ID, 'Фефилатьева Маргарита'),
            (SVETA_VK_ID, 'Яскевич Светлана'),
            (PLAYER_A_VK_ID, 'Игрок Анна'),
            (PLAYER_B_VK_ID, 'Игрок Вера'),
        ]:
            await self.reg.self_register(
                RegistrationData(vk_id=vk_id, full_name=name)
            )
            await self.reg.approve(ADMIN_VK_ID, vk_id)
        for vk_id in (SEDOVA_VK_ID, RITA_VK_ID):
            await self.roles.assign_role(ADMIN_VK_ID, vk_id, RoleName.COLLECTOR)

    async def set_paid_at(self, user_vk_id: int, moment: datetime) -> None:
        """Переносит отметку оплаты абонемента на заданный момент (UTC)."""
        async with self.uow_factory() as uow:
            user = await uow.users.get_by_vk_id(user_vk_id)
            sub = await uow.subscriptions.get_for_month(SEPTEMBER)
            payment = await uow.subscriptions.get_payment(sub.id, user.id)
            payment.marked_at = moment
            await uow.subscriptions.update_payment(payment)
            await uow.commit()

    async def set_visits_paid_at(self, moment: datetime) -> None:
        async with self.uow_factory() as uow:
            for visit in await uow.one_time.visits_in_month(SEPTEMBER):
                visit.marked_at = moment
                await uow.one_time.update_visit(visit)
            await uow.commit()


async def _september(uow_factory: Callable[[], UnitOfWork]) -> _Club:
    club = _Club(uow_factory)
    await club.set_up()
    # Абонемент 2450, Анна платит 2100 (350 зачтено разовым) — оба Седовой.
    await club.subs.register_voting(
        SEDOVA_VK_ID, SEPTEMBER, [str(PLAYER_A_VK_ID), str(PLAYER_B_VK_ID)]
    )
    await club.subs.set_fact_amount(SEDOVA_VK_ID, SEPTEMBER, Decimal('2450'))
    for vk_id in (PLAYER_A_VK_ID, PLAYER_B_VK_ID):
        await club.subs.mark_payment(
            SEDOVA_VK_ID, SEPTEMBER, str(vk_id), paid=True
        )
        await club.set_paid_at(vk_id, datetime(2026, 9, 2, 12, tzinfo=UTC))
    async with uow_factory() as uow:
        user = await uow.users.get_by_vk_id(PLAYER_A_VK_ID)
        sub = await uow.subscriptions.get_for_month(SEPTEMBER)
        payment = await uow.subscriptions.get_payment(sub.id, user.id)
        payment.amount = Decimal('2100')
        await uow.subscriptions.update_payment(payment)
        await uow.commit()

    # Разовые: два посещения собрала Рита.
    await club.one_time.register_visits(
        RITA_VK_ID, [str(PLAYER_A_VK_ID), str(PLAYER_B_VK_ID)], date(2026, 9, 3)
    )
    for vk_id in (PLAYER_A_VK_ID, PLAYER_B_VK_ID):
        await club.one_time.mark_oldest_unpaid(RITA_VK_ID, str(vk_id))
    await club.set_visits_paid_at(datetime(2026, 9, 3, 18, tzinfo=UTC))

    # Начальные остатки на 19.08 (как в таблице).
    for target, amount in [
        ('Седова', '1800'),
        ('Фефилатьева', '5700'),
        ('Яскевич', '870'),
    ]:
        await club.finance.add_adjustment(
            ADMIN_VK_ID,
            adjusted_on=date(2026, 8, 19),
            target=target,
            amount=Decimal(amount),
            reason='Остаток по таблице на 19.08.2026',
        )
    await club.finance.add_expense(
        SEDOVA_VK_ID,
        spent_on=date(2026, 9, 5),
        category=ExpenseCategory.COACH,
        description='Оплата тренер Елена',
        amount=Decimal('3000'),
    )
    await club.finance.add_transfer(
        RITA_VK_ID,
        transferred_on=date(2026, 9, 10),
        to='Седова',
        amount=Decimal('500'),
    )
    return club


@pytest.mark.asyncio
async def test_balances_at_month_end(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    club = await _september(uow_factory)
    report = await club.balances.balances(RITA_VK_ID, date(2026, 9, 30))
    by_name = {row.name: row.balance for row in report.rows}

    sedova = by_name['Седова Ольга']
    assert sedova.opening == Decimal('1800')
    assert sedova.subscriptions == Decimal('4550')  # 2450 + 2100
    assert sedova.expenses == Decimal('3000')
    assert sedova.transfers == Decimal('500')
    assert sedova.closing == Decimal('3850')

    rita = by_name['Фефилатьева Маргарита']
    assert rita.opening == Decimal('5700')
    assert rita.one_time == Decimal('700')
    assert rita.transfers == Decimal('-500')
    assert rita.closing == Decimal('5900')

    assert by_name['Яскевич Светлана'].closing == Decimal('870')
    assert report.total == Decimal('10620')
    assert report.start == date(2026, 9, 1)
    assert [row.name for row in report.rows] == sorted(by_name)


@pytest.mark.asyncio
async def test_balances_on_earlier_date_ignore_later_movements(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    club = await _september(uow_factory)
    report = await club.balances.balances(SEDOVA_VK_ID, date(2026, 9, 2))
    by_name = {row.name: row.balance for row in report.rows}
    assert by_name['Седова Ольга'].closing == Decimal('6350')  # 1800 + 4550
    # Разовые (03.09) и передача (10.09) ещё не случились.
    assert by_name['Фефилатьева Маргарита'].closing == Decimal('5700')


@pytest.mark.asyncio
async def test_payment_after_midnight_moscow_counts_next_day(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    club = await _september(uow_factory)
    # 31.08 22:30 UTC — это уже 01.09 01:30 по Москве.
    await club.set_paid_at(
        PLAYER_B_VK_ID, datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    )

    aug = await club.balances.balances(SEDOVA_VK_ID, date(2026, 8, 31))
    sedova_aug = {r.name: r.balance for r in aug.rows}['Седова Ольга']
    assert sedova_aug.closing == Decimal('1800')

    sep = await club.balances.balances(
        SEDOVA_VK_ID, date(2026, 9, 1), start=date(2026, 9, 1)
    )
    sedova_sep = {r.name: r.balance for r in sep.rows}['Седова Ольга']
    assert sedova_sep.opening == Decimal('1800')
    assert sedova_sep.subscriptions == Decimal('2450')


@pytest.mark.asyncio
async def test_collector_without_movements_is_listed(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    club = _Club(uow_factory)
    await club.set_up()
    report = await club.balances.balances(SEDOVA_VK_ID, date(2026, 9, 30))
    assert {row.name: row.balance.closing for row in report.rows} == {
        'Седова Ольга': Decimal('0'),
        'Фефилатьева Маргарита': Decimal('0'),
    }


@pytest.mark.asyncio
async def test_my_balance_and_permissions(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    club = await _september(uow_factory)
    row = await club.balances.my_balance(RITA_VK_ID, date(2026, 9, 30))
    assert row.name == 'Фефилатьева Маргарита'
    assert row.balance.closing == Decimal('5900')

    with pytest.raises(PermissionDeniedError):
        await club.balances.balances(PLAYER_A_VK_ID, date(2026, 9, 30))
    with pytest.raises(NotFoundError):
        await club.balances.my_balance(ADMIN_VK_ID, date(2026, 9, 30))


@pytest.mark.asyncio
async def test_chat_report_text(uow_factory: Callable[[], UnitOfWork]) -> None:
    club = await _september(uow_factory)
    report = await club.balances.balances(RITA_VK_ID, date(2026, 9, 30))
    text = _format_report(report)
    assert 'Деньги клуба на руках на 30.09.2026' in text
    assert 'Седова Ольга: 3\xa0850 ₽' in text
    assert (
        'на 01.09: 1\xa0800 · +абонементы 4\xa0550 · −расходы 3\xa0000 · '
        '+передачи 500'
    ) in text
    assert 'Фефилатьева Маргарита: 5\xa0900 ₽' in text
    assert 'Итого на руках: 10\xa0620 ₽' in text
