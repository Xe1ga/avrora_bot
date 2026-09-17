"""Тесты игрока, добавленного вручную без аккаунта ВК (vk_id = None)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from avrora_bot.adapters.database.seed import seed_reference_data
from avrora_bot.application.services.user_lookup import resolve_user
from avrora_bot.application.use_cases.one_time import OneTimeUseCases
from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.application.use_cases.subscriptions import SubscriptionUseCases
from avrora_bot.application.use_cases.user_management import (
    UserManagementUseCases,
)
from avrora_bot.domain.enums import PaymentStatus, RoleName, UserStatus
from avrora_bot.domain.errors import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.value_objects import MonthPeriod
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1
COLLECTOR_VK_ID = 101


async def _prepare(
    uow_factory: Callable[[], UnitOfWork], vk: FakeVkGateway
) -> tuple[RegistrationUseCases, UserManagementUseCases]:
    async with uow_factory() as uow:
        await seed_reference_data(uow)
        await uow.commit()
    reg = RegistrationUseCases(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    await reg.self_register(
        RegistrationData(vk_id=COLLECTOR_VK_ID, full_name='Иванов Пётр')
    )
    await reg.approve(ADMIN_VK_ID, COLLECTOR_VK_ID)
    await roles.assign_role(ADMIN_VK_ID, COLLECTOR_VK_ID, RoleName.COLLECTOR)
    return reg, UserManagementUseCases(uow_factory, vk)


@pytest.mark.asyncio
async def test_admin_add_player_without_vk_is_active_with_player_role(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg, _ = await _prepare(uow_factory, vk)

    player = await reg.admin_add_player_without_vk(ADMIN_VK_ID, 'Петров Олег')

    assert player.vk_id is None
    assert player.status is UserStatus.ACTIVE
    # Роль назначается после создания строки — на самой возвращённой
    # сущности (как и у approve()/admin_add_user()) она не отражается,
    # поэтому проверяем отдельным запросом.
    async with uow_factory() as uow:
        assert RoleName.PLAYER in await uow.roles.roles_of(player.id)


@pytest.mark.asyncio
async def test_admin_add_player_without_vk_requires_admin(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg, _ = await _prepare(uow_factory, vk)

    with pytest.raises(PermissionDeniedError):
        await reg.admin_add_player_without_vk(COLLECTOR_VK_ID, 'Петров Олег')


@pytest.mark.asyncio
async def test_resolve_user_finds_manual_player_by_name_only(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg, _ = await _prepare(uow_factory, vk)
    player = await reg.admin_add_player_without_vk(ADMIN_VK_ID, 'Петров Олег')

    async with uow_factory() as uow:
        found = await resolve_user(uow, 'петров')
    assert found.id == player.id

    # vk_id у такого игрока нет — по числу его не найти.
    async with uow_factory() as uow:
        with pytest.raises(NotFoundError):
            await resolve_user(uow, '999999')


@pytest.mark.asyncio
async def test_get_by_vk_id_none_does_not_match_manual_players(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    """Два безВК-игрока не должны путаться друг с другом через vk_id=None."""
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg, _ = await _prepare(uow_factory, vk)
    await reg.admin_add_player_without_vk(ADMIN_VK_ID, 'Петров Олег')
    await reg.admin_add_player_without_vk(ADMIN_VK_ID, 'Сидоров Лев')

    async with uow_factory() as uow:
        assert await uow.users.get_by_vk_id(None) is None


@pytest.mark.asyncio
async def test_admin_can_edit_manual_player_found_by_name(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg, users = await _prepare(uow_factory, vk)
    await reg.admin_add_player_without_vk(ADMIN_VK_ID, 'Петров Олег')

    player = await users.get_user(ADMIN_VK_ID, 'Петров Олег')
    assert player.vk_id is None

    updated = await users.set_phone(ADMIN_VK_ID, player.id, '+70001112233')
    assert updated.phone == '+70001112233'
    updated = await users.set_birthdate(ADMIN_VK_ID, player.id, date(1995, 5, 1))
    assert updated.birthdate == date(1995, 5, 1)


@pytest.mark.asyncio
async def test_manual_player_tracked_in_subscription_voting(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg, _ = await _prepare(uow_factory, vk)
    player = await reg.admin_add_player_without_vk(ADMIN_VK_ID, 'Петров Олег')
    subs = SubscriptionUseCases(uow_factory, vk)
    period = MonthPeriod(2026, 9)

    await subs.register_voting(
        COLLECTOR_VK_ID, period, [str(COLLECTOR_VK_ID), 'Петров Олег']
    )
    updated = await subs.mark_payment(
        COLLECTOR_VK_ID, period, 'Петров Олег', paid=True
    )
    assert updated.id == player.id

    summary = await subs.month_summary(period)
    paid_ids = {r.user.id for r in summary.rows if r.status is PaymentStatus.PAID}
    assert player.id in paid_ids


@pytest.mark.asyncio
async def test_manual_player_tracked_in_one_time_visits(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg, _ = await _prepare(uow_factory, vk)
    player = await reg.admin_add_player_without_vk(ADMIN_VK_ID, 'Петров Олег')
    one_time = OneTimeUseCases(uow_factory, vk)

    [outcome] = await one_time.register_visits(
        COLLECTOR_VK_ID, ['Петров Олег'], date(2026, 9, 5)
    )
    assert outcome.user.id == player.id
    assert outcome.user.vk_id is None
    assert outcome.visit.amount == Decimal('350')

    paid = await one_time.mark_oldest_unpaid(COLLECTOR_VK_ID, 'Петров Олег')
    assert paid.visit.status is PaymentStatus.PAID
    assert paid.visit.marked_by_vk_id == COLLECTOR_VK_ID  # принял сборщик


@pytest.mark.asyncio
async def test_manual_player_cannot_be_recorded_as_payment_receiver(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    """marked_by_vk_id хранит vk_id — безВК-игрока так не отличить от «не
    принято», поэтому назначать его получателем оплаты запрещено явно."""
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg, _ = await _prepare(uow_factory, vk)
    await reg.admin_add_player_without_vk(ADMIN_VK_ID, 'Петров Олег')
    one_time = OneTimeUseCases(uow_factory, vk)

    [outcome] = await one_time.register_visits(
        COLLECTOR_VK_ID, [str(COLLECTOR_VK_ID)], date(2026, 9, 5)
    )

    with pytest.raises(ValidationError):
        await one_time.set_visit_marked_by(
            COLLECTOR_VK_ID, outcome.visit.id, 'Петров Олег'
        )
