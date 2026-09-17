"""Тесты редактирования данных пользователя администратором."""

from collections.abc import Callable
from datetime import date

import pytest

from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.application.use_cases.user_management import (
    UserManagementUseCases,
)
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import NotFoundError, PermissionDeniedError
from avrora_bot.domain.ports.uow import UnitOfWork
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1
PLAYER_VK_ID = 101
OTHER_PLAYER_VK_ID = 102


async def _prepare(
    uow_factory: Callable[[], UnitOfWork], vk: FakeVkGateway
) -> UserManagementUseCases:
    reg = RegistrationUseCases(uow_factory, vk)
    await reg.self_register(
        RegistrationData(
            vk_id=PLAYER_VK_ID,
            full_name='Иван Иванов',
            birthdate=date(2000, 1, 1),
            height_cm=180,
            phone='+70000000000',
        )
    )
    return UserManagementUseCases(uow_factory, vk)


@pytest.mark.asyncio
async def test_admin_can_edit_user_fields(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    users = await _prepare(uow_factory, vk)

    updated = await users.set_full_name(
        ADMIN_VK_ID, PLAYER_VK_ID, 'Пётр Петров'
    )
    assert updated.full_name == 'Пётр Петров'

    updated = await users.set_phone(ADMIN_VK_ID, PLAYER_VK_ID, None)
    assert updated.phone is None

    updated = await users.set_birthdate(
        ADMIN_VK_ID, PLAYER_VK_ID, date(1999, 12, 31)
    )
    assert updated.birthdate == date(1999, 12, 31)

    updated = await users.set_height(ADMIN_VK_ID, PLAYER_VK_ID, 190)
    assert updated.height_cm == 190

    fetched = await users.get_user(ADMIN_VK_ID, PLAYER_VK_ID)
    assert fetched.full_name == 'Пётр Петров'
    assert fetched.phone is None
    assert fetched.birthdate == date(1999, 12, 31)
    assert fetched.height_cm == 190


@pytest.mark.asyncio
async def test_non_admin_cannot_edit_user(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    users = await _prepare(uow_factory, vk)

    with pytest.raises(PermissionDeniedError):
        await users.set_full_name(PLAYER_VK_ID, PLAYER_VK_ID, 'Хакер')

    assert RoleName.ADMIN not in await users.effective_roles(PLAYER_VK_ID)
    assert RoleName.ADMIN in await users.effective_roles(ADMIN_VK_ID)


@pytest.mark.asyncio
async def test_edit_unknown_user_raises_not_found(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    users = await _prepare(uow_factory, vk)

    with pytest.raises(NotFoundError):
        await users.get_user(ADMIN_VK_ID, 999999)


@pytest.mark.asyncio
async def test_list_players_returns_approved_players_sorted_by_name(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    users = await _prepare(uow_factory, vk)
    reg = RegistrationUseCases(uow_factory, vk)
    await reg.self_register(
        RegistrationData(vk_id=OTHER_PLAYER_VK_ID, full_name='Борис Борисов')
    )
    # Пока заявка не подтверждена — роли player нет, в список не попадает.
    assert await users.list_players(ADMIN_VK_ID) == []

    await reg.approve(ADMIN_VK_ID, PLAYER_VK_ID)
    await reg.approve(ADMIN_VK_ID, OTHER_PLAYER_VK_ID)

    players = await users.list_players(ADMIN_VK_ID)
    assert [p.full_name for p in players] == ['Борис Борисов', 'Иван Иванов']
    assert players[1].vk_id == PLAYER_VK_ID
    assert players[1].birthdate == date(2000, 1, 1)
    assert players[1].height_cm == 180
    assert players[1].phone == '+70000000000'


@pytest.mark.asyncio
async def test_list_players_allows_collector_and_curator(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    users = await _prepare(uow_factory, vk)
    reg = RegistrationUseCases(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    await reg.approve(ADMIN_VK_ID, PLAYER_VK_ID)
    await reg.self_register(
        RegistrationData(vk_id=OTHER_PLAYER_VK_ID, full_name='Сборщик Сборщиков')
    )
    await reg.approve(ADMIN_VK_ID, OTHER_PLAYER_VK_ID)
    await roles.assign_role(ADMIN_VK_ID, OTHER_PLAYER_VK_ID, RoleName.COLLECTOR)

    players = await users.list_players(OTHER_PLAYER_VK_ID)
    assert {p.vk_id for p in players} == {PLAYER_VK_ID, OTHER_PLAYER_VK_ID}
    by_vk_id = {p.vk_id: p for p in players}
    # Роли отражают полный набор, а не только player, использованный
    # для отбора выше мы ещё назначили COLLECTOR.
    assert by_vk_id[PLAYER_VK_ID].roles == {RoleName.PLAYER}
    assert by_vk_id[OTHER_PLAYER_VK_ID].roles == {
        RoleName.PLAYER,
        RoleName.COLLECTOR,
    }


@pytest.mark.asyncio
async def test_list_players_denies_plain_player(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    users = await _prepare(uow_factory, vk)
    reg = RegistrationUseCases(uow_factory, vk)
    await reg.approve(ADMIN_VK_ID, PLAYER_VK_ID)

    with pytest.raises(PermissionDeniedError):
        await users.list_players(PLAYER_VK_ID)
