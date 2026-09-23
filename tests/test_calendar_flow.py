"""Тесты календаря: фильтр прошедших событий и автогенерация тренировок."""

from collections.abc import Callable
from datetime import date, time

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
from avrora_bot.domain.errors import NotFoundError, PermissionDeniedError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.value_objects import MonthPeriod
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1
CURATOR_VK_ID = 101
PLAYER_VK_ID = 102

# Сентябрь 2026 по «Оплата абонементов.md»: 5 вторников (по 2 тренировки),
# 4 четверга, 4 пятницы — итого 18 тренировок. 1 сентября 2026 — вторник.
_SEPTEMBER_2026_TRAININGS = 18


async def _prepare(
    uow_factory: Callable[[], UnitOfWork], vk: FakeVkGateway
) -> CalendarUseCases:
    async with uow_factory() as uow:
        await seed_reference_data(uow)
        await uow.commit()
    reg = RegistrationUseCases(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    for vk_id, name in [
        (CURATOR_VK_ID, 'Куратор Тестов'),
        (PLAYER_VK_ID, 'Игрок Тестов'),
    ]:
        await reg.self_register(RegistrationData(vk_id=vk_id, full_name=name))
        await reg.approve(ADMIN_VK_ID, vk_id)
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


@pytest.mark.asyncio
async def test_generate_month_trainings_creates_from_schedule(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    calendar = await _prepare(uow_factory, vk)
    period = MonthPeriod(2026, 9)

    result = await calendar.generate_month_trainings(CURATOR_VK_ID, period)

    assert len(result.created) == _SEPTEMBER_2026_TRAININGS
    assert result.skipped == 0
    assert all(ev.event_type is EventType.TRAINING for ev in result.created)

    events = await calendar.list_month(period)
    assert len(events) == _SEPTEMBER_2026_TRAININGS
    # 1 сентября 2026 — вторник: должно быть 2 тренировки, 19:00 и 20:30.
    tuesday_times = sorted(
        ev.event_time for ev in events if ev.event_date == date(2026, 9, 1)
    )
    assert tuesday_times == [time(19, 0), time(20, 30)]


@pytest.mark.asyncio
async def test_generate_month_trainings_is_idempotent(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    calendar = await _prepare(uow_factory, vk)
    period = MonthPeriod(2026, 9)
    await calendar.generate_month_trainings(CURATOR_VK_ID, period)

    result = await calendar.generate_month_trainings(CURATOR_VK_ID, period)

    assert result.created == []
    assert result.skipped == _SEPTEMBER_2026_TRAININGS
    events = await calendar.list_month(period)
    assert len(events) == _SEPTEMBER_2026_TRAININGS


@pytest.mark.asyncio
async def test_generate_month_trainings_fills_only_missing(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    """Ручное событие в тот же день/час не задваивается при генерации."""
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    calendar = await _prepare(uow_factory, vk)
    period = MonthPeriod(2026, 9)
    manual = await calendar.add_event(
        CURATOR_VK_ID,
        EventData(
            event_date=date(2026, 9, 1),
            event_type=EventType.TRAINING,
            event_time=time(19, 0),
        ),
    )
    assert manual.event_time == time(19, 0)

    result = await calendar.generate_month_trainings(CURATOR_VK_ID, period)

    # 19:00-слот 1 сентября уже существовал (ручной) — досоздан только
    # оставшийся 20:30, поэтому 17 новых при 18 всего.
    assert len(result.created) == _SEPTEMBER_2026_TRAININGS - 1
    assert result.skipped == 1
    events = await calendar.list_month(period)
    assert len(events) == _SEPTEMBER_2026_TRAININGS


@pytest.mark.asyncio
async def test_generate_month_trainings_requires_curator(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    calendar = await _prepare(uow_factory, vk)
    period = MonthPeriod(2026, 9)

    with pytest.raises(PermissionDeniedError):
        await calendar.generate_month_trainings(PLAYER_VK_ID, period)


@pytest.mark.asyncio
async def test_generate_month_trainings_requires_schedule(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    """Без сида расписания (пустой ``schedule_template``) — NotFoundError."""
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg = RegistrationUseCases(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    await reg.self_register(
        RegistrationData(vk_id=CURATOR_VK_ID, full_name='Куратор Тестов')
    )
    await reg.approve(ADMIN_VK_ID, CURATOR_VK_ID)
    await roles.assign_role(ADMIN_VK_ID, CURATOR_VK_ID, RoleName.CURATOR)
    calendar = CalendarUseCases(uow_factory, vk)

    with pytest.raises(NotFoundError):
        await calendar.generate_month_trainings(
            CURATOR_VK_ID, MonthPeriod(2026, 9)
        )


def test_month_period_next_month_rolls_over_year() -> None:
    assert MonthPeriod(2026, 12).next_month() == MonthPeriod(2027, 1)
    assert MonthPeriod(2026, 9).next_month() == MonthPeriod(2026, 10)
