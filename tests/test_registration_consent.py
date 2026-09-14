"""Тесты фиксации согласия на обработку персональных данных (ТЗ 3.6, 152-ФЗ)."""

from collections.abc import Callable
from datetime import date

import pytest

from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.domain.ports.uow import UnitOfWork
from tests.conftest import FakeVkGateway

PLAYER_VK_ID = 101


@pytest.mark.asyncio
async def test_self_register_records_consent(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway()
    reg = RegistrationUseCases(uow_factory, vk)

    user = await reg.self_register(
        RegistrationData(
            vk_id=PLAYER_VK_ID,
            full_name='Иван Иванов',
            birthdate=date(2000, 1, 1),
            height_cm=180,
            phone='+70000000000',
            consent_version='1.0',
        )
    )

    async with uow_factory() as uow:
        records = await uow.consents.list_for_user(user.id)

    assert len(records) == 1
    assert records[0].user_id == user.id
    assert records[0].version == '1.0'
    assert records[0].given_at is not None


@pytest.mark.asyncio
async def test_self_register_without_consent_version_writes_nothing(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    # Ручное добавление администратором (admin_add_user) не проходит через
    # чат-шаг согласия — consent_version там не передаётся, и это не
    # должно приводить к ошибке или фиктивной записи в user_consents.
    vk = FakeVkGateway()
    reg = RegistrationUseCases(uow_factory, vk)

    user = await reg.self_register(
        RegistrationData(vk_id=PLAYER_VK_ID, full_name='Иван Иванов')
    )

    async with uow_factory() as uow:
        records = await uow.consents.list_for_user(user.id)

    assert records == []
