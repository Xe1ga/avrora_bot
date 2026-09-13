"""Тесты редактирования данных пользователя администратором."""

from collections.abc import Callable
from datetime import date

import pytest

from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.application.use_cases.user_management import (
    UserManagementUseCases,
)
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import NotFoundError, PermissionDeniedError
from avrora_bot.domain.ports.uow import UnitOfWork
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1
PLAYER_VK_ID = 101


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
