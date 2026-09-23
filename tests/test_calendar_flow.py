"""Тесты календаря: просмотр месяца и фильтр прошедших событий."""

from collections.abc import Callable
from datetime import date

import pytest

from avrora_bot.adapters.database.seed import seed_reference_data
from avrora_bot.application.use_cases.calendar import (
    CalendarUseCases,
    EventData,
)
from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.domain.enums import EventType, RoleName
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.value_objects import MonthPeriod
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1
CURATOR_VK_ID = 101


async def _prepare(
    uow_factory: Callable[[], UnitOfWork], vk: FakeVkGateway
) -> CalendarUseCases:
    async with uow_factory() as uow:
        await seed_reference_data(uow)
        await uow.commit()
    reg = RegistrationUseCases(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    await reg.self_register(
        RegistrationData(vk_id=CURATOR_VK_ID, full_name='Куратор Тестов')
    )
    await reg.approve(ADMIN_VK_ID, CURATOR_VK_ID)
    await roles.assign_role(ADMIN_VK_ID, CURATOR_VK_ID, RoleName.CURATOR)
    return CalendarUseCases(uow_factory, vk)


@pytest.mark.asyncio
async def test_list_month_without_from_date_returns_all_events(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    calendar = await _prepare(uow_factory, vk)
    period = MonthPeriod(2026, 9)
    await calendar.add_event(
        CURATOR_VK_ID,
        EventData(event_date=date(2026, 9, 5), event_type=EventType.TRAINING),
    )
    await calendar.add_event(
        CURATOR_VK_ID,
        EventData(event_date=date(2026, 9, 25), event_type=EventType.GAME),
    )

    events = await calendar.list_month(period)

    assert {ev.event_date for ev in events} == {
        date(2026, 9, 5),
        date(2026, 9, 25),
    }


@pytest.mark.asyncio
async def test_list_month_with_from_date_hides_past_events(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    calendar = await _prepare(uow_factory, vk)
    period = MonthPeriod(2026, 9)
    await calendar.add_event(
        CURATOR_VK_ID,
        EventData(event_date=date(2026, 9, 5), event_type=EventType.TRAINING),
    )
    await calendar.add_event(
        CURATOR_VK_ID,
        EventData(event_date=date(2026, 9, 22), event_type=EventType.TRAINING),
    )
    await calendar.add_event(
        CURATOR_VK_ID,
        EventData(event_date=date(2026, 9, 25), event_type=EventType.GAME),
    )

    events = await calendar.list_month(period, from_date=date(2026, 9, 22))

    # 5 сентября уже прошло — его быть не должно; сегодняшнее (22-е) и
    # будущее (25-е) остаются.
    assert {ev.event_date for ev in events} == {
        date(2026, 9, 22),
        date(2026, 9, 25),
    }


@pytest.mark.asyncio
async def test_list_month_with_from_date_after_all_events_is_empty(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    calendar = await _prepare(uow_factory, vk)
    period = MonthPeriod(2026, 9)
    await calendar.add_event(
        CURATOR_VK_ID,
        EventData(event_date=date(2026, 9, 5), event_type=EventType.TRAINING),
    )

    events = await calendar.list_month(period, from_date=date(2026, 9, 30))

    assert events == []
