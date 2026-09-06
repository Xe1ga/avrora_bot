"""Интеграционные тесты сценария абонементов (application + БД)."""

from collections.abc import Callable
from decimal import Decimal

import pytest

from avrora_bot.adapters.database.seed import seed_reference_data
from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.application.use_cases.subscriptions import SubscriptionUseCases
from avrora_bot.domain.enums import PaymentStatus, RoleName
from avrora_bot.domain.errors import PermissionDeniedError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.value_objects import MonthPeriod
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1


async def _prepare(
    uow_factory: Callable[[], UnitOfWork], vk: FakeVkGateway
) -> tuple[RegistrationUseCases, RoleUseCases, SubscriptionUseCases]:
    async with uow_factory() as uow:
        await seed_reference_data(uow)
        await uow.commit()
    reg = RegistrationUseCases(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    subs = SubscriptionUseCases(uow_factory, vk)
    for vk_id, name in [(101, 'A A'), (102, 'B B'), (103, 'C C')]:
        await reg.self_register(RegistrationData(vk_id=vk_id, full_name=name))
        await reg.approve(ADMIN_VK_ID, vk_id)
    await roles.assign_role(ADMIN_VK_ID, 101, RoleName.COLLECTOR)
    return reg, roles, subs


@pytest.mark.asyncio
async def test_full_subscription_flow(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    _, _, subs = await _prepare(uow_factory, vk)
    period = MonthPeriod(2026, 9)

    calc = await subs.calculate(101, period, voters=3)
    assert calc.cost.total == Decimal('65750.000')
    assert calc.per_person_amount == Decimal('21917')  # 65750/3 ceil

    await subs.register_voting(101, period, [101, 102, 103])
    await subs.override_amount(101, period, Decimal('22000'))
    await subs.mark_payment(101, period, 101, paid=True)
    await subs.mark_payment(101, period, 102, paid=True)

    summary = await subs.month_summary(period)
    assert summary.paid_count == 2
    assert summary.collected == Decimal('44000.00')
    paid_names = {
        r.user.full_name for r in summary.rows if r.status is PaymentStatus.PAID
    }
    assert paid_names == {'A A', 'B B'}


@pytest.mark.asyncio
async def test_non_collector_cannot_mark_payment(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    _, _, subs = await _prepare(uow_factory, vk)
    period = MonthPeriod(2026, 9)
    await subs.register_voting(101, period, [101, 102, 103])

    with pytest.raises(PermissionDeniedError):
        await subs.mark_payment(102, period, 103, paid=True)
