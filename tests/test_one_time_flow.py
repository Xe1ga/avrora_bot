"""Тесты сценария разовых посещений (application + БД)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from avrora_bot.adapters.database.seed import seed_reference_data
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.application.use_cases.one_time import OneTimeUseCases
from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.domain.enums import PaymentStatus, RoleName
from avrora_bot.domain.errors import NotFoundError, ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1
COLLECTOR_VK_ID = 101
PLAYER_VK_ID = 102


async def _prepare(
    uow_factory: Callable[[], UnitOfWork], vk: FakeVkGateway
) -> tuple[RegistrationUseCases, OneTimeUseCases]:
    async with uow_factory() as uow:
        await seed_reference_data(uow)
        await uow.commit()
    reg = RegistrationUseCases(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    for vk_id, name in [
        (COLLECTOR_VK_ID, 'Иванов Пётр'),
        (PLAYER_VK_ID, 'Петров Олег'),
    ]:
        await reg.self_register(RegistrationData(vk_id=vk_id, full_name=name))
        await reg.approve(ADMIN_VK_ID, vk_id)
    await roles.assign_role(ADMIN_VK_ID, COLLECTOR_VK_ID, RoleName.COLLECTOR)
    return reg, OneTimeUseCases(uow_factory, vk)


@pytest.mark.asyncio
async def test_register_visits_resolves_targets_by_vk_id_and_name(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg, one_time = await _prepare(uow_factory, vk)
    await reg.self_register(RegistrationData(vk_id=103, full_name='Сидоров Лев'))
    await reg.approve(ADMIN_VK_ID, 103)

    outcomes = await one_time.register_visits(
        COLLECTOR_VK_ID,
        [str(PLAYER_VK_ID), 'сидоров'],
        date(2026, 9, 5),
    )
    assert {o.user.vk_id for o in outcomes} == {PLAYER_VK_ID, 103}
    assert all(o.visit.amount == Decimal('350') for o in outcomes)


@pytest.mark.asyncio
async def test_register_visits_dedupes_same_person_by_id_and_name(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    _, one_time = await _prepare(uow_factory, vk)

    outcomes = await one_time.register_visits(
        COLLECTOR_VK_ID,
        [str(PLAYER_VK_ID), 'петров'],
        date(2026, 9, 5),
    )
    assert len(outcomes) == 1
    assert outcomes[0].user.vk_id == PLAYER_VK_ID


@pytest.mark.asyncio
async def test_register_visits_rejects_whole_batch_on_unknown_target(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    _, one_time = await _prepare(uow_factory, vk)

    with pytest.raises(ValidationError, match='999999'):
        await one_time.register_visits(
            COLLECTOR_VK_ID,
            [str(PLAYER_VK_ID), '999999'],
            date(2026, 9, 5),
        )

    # Ни одно посещение из отклонённого списка не должно быть сохранено.
    with pytest.raises(NotFoundError):
        await one_time.mark_oldest_unpaid(COLLECTOR_VK_ID, str(PLAYER_VK_ID))


@pytest.mark.asyncio
async def test_register_visits_without_tariff_raises_not_found(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    _, one_time = await _prepare(uow_factory, vk)

    with pytest.raises(NotFoundError):
        await one_time.register_visits(
            COLLECTOR_VK_ID, [str(PLAYER_VK_ID)], date(2020, 1, 1)
        )


@pytest.mark.asyncio
async def test_register_visits_ambiguous_name_raises_validation_error(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg, one_time = await _prepare(uow_factory, vk)
    await reg.self_register(RegistrationData(vk_id=103, full_name='Петров Иван'))
    await reg.approve(ADMIN_VK_ID, 103)

    with pytest.raises(ValidationError):
        await one_time.register_visits(
            COLLECTOR_VK_ID, ['петров'], date(2026, 9, 5)
        )


@pytest.mark.asyncio
async def test_mark_oldest_unpaid_pays_earliest_visit_first(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    _, one_time = await _prepare(uow_factory, vk)
    [older] = await one_time.register_visits(
        COLLECTOR_VK_ID, [str(PLAYER_VK_ID)], date(2026, 9, 3)
    )
    [newer] = await one_time.register_visits(
        COLLECTOR_VK_ID, [str(PLAYER_VK_ID)], date(2026, 9, 20)
    )

    outcome = await one_time.mark_oldest_unpaid(COLLECTOR_VK_ID, 'Петров')
    assert outcome.visit.id == older.visit.id
    assert outcome.visit.status is PaymentStatus.PAID

    # Второй вызов — оплачивается следующий неоплаченный (тот, что новее).
    outcome2 = await one_time.mark_oldest_unpaid(COLLECTOR_VK_ID, 'Петров')
    assert outcome2.visit.id == newer.visit.id


@pytest.mark.asyncio
async def test_mark_oldest_unpaid_raises_when_nothing_unpaid(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    _, one_time = await _prepare(uow_factory, vk)

    with pytest.raises(NotFoundError):
        await one_time.mark_oldest_unpaid(COLLECTOR_VK_ID, str(PLAYER_VK_ID))


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('12345', ['12345']),
        ('12345, Иванов Пётр', ['12345', 'Иванов Пётр']),
        ('Иванов Пётр\nПетров Олег', ['Иванов Пётр', 'Петров Олег']),
        ('  Иванов  \n\n, 12345', ['Иванов', '12345']),
    ],
)
def test_parse_targets(raw: str, expected: list[str]) -> None:
    assert helpers.parse_targets(raw) == expected


def test_parse_targets_rejects_empty_list() -> None:
    with pytest.raises(ValidationError):
        helpers.parse_targets('   \n,  ')
