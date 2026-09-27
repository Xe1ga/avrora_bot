"""Тесты статусов событий календаря: отмена, автозавершение, показ в чате."""

import importlib.util
from collections.abc import Callable
from datetime import date, datetime, time
from pathlib import Path

import pytest

from avrora_bot.application.use_cases.calendar import (
    CalendarUseCases,
    EventData,
    chat_visible_status,
    complete_finished_events,
)
from avrora_bot.domain.entities import CalendarEvent, ScheduleSlot
from avrora_bot.domain.enums import EventStatus, EventType, Weekday
from avrora_bot.domain.errors import PermissionDeniedError, ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.services.event_completion import event_end
from avrora_bot.domain.value_objects import MonthPeriod
from tests.conftest import FakeVkGateway
from tests.test_calendar_flow import (
    ADMIN_VK_ID,
    CURATOR_VK_ID,
    PLAYER_VK_ID,
    _prepare,
)

_SLOTS = [
    ScheduleSlot(weekday=Weekday.TUESDAY, start=time(19, 0), end=time(20, 30)),
    ScheduleSlot(weekday=Weekday.TUESDAY, start=time(20, 30), end=time(22, 0)),
]


def _event(
    day: date,
    at: time | None,
    event_type: EventType = EventType.TRAINING,
) -> CalendarEvent:
    return CalendarEvent(
        event_date=day,
        event_time=at,
        event_type=event_type,
        place=None,
        comment=None,
        author_vk_id=CURATOR_VK_ID,
    )


# ── Правила окончания события ────────────────────────────────────────────


def test_event_end_training_uses_schedule_slot_end() -> None:
    # 1 сентября 2026 — вторник, слот 19:00–20:30.
    ev = _event(date(2026, 9, 1), time(19, 0))
    assert event_end(ev, _SLOTS) == datetime(2026, 9, 1, 20, 30)


def test_event_end_training_outside_template_lasts_two_hours() -> None:
    ev = _event(date(2026, 9, 2), time(18, 0))  # среда — слота нет
    assert event_end(ev, _SLOTS) == datetime(2026, 9, 2, 20, 0)


def test_event_end_game_lasts_two_hours_even_on_slot_time() -> None:
    ev = _event(date(2026, 9, 1), time(19, 0), EventType.GAME)
    assert event_end(ev, _SLOTS) == datetime(2026, 9, 1, 21, 0)


def test_event_end_without_time_is_end_of_day() -> None:
    ev = _event(date(2026, 10, 10), None, EventType.GAME)
    assert event_end(ev, _SLOTS) == datetime(2026, 10, 11, 0, 0)


# ── Правило показа в чате ────────────────────────────────────────────────


def test_chat_visible_status_by_month() -> None:
    today = date(2026, 10, 15)
    assert chat_visible_status(MonthPeriod(2026, 9), today) is (
        EventStatus.DONE
    )
    assert chat_visible_status(MonthPeriod(2026, 10), today) is (
        EventStatus.PLANNED
    )
    assert chat_visible_status(MonthPeriod(2026, 11), today) is (
        EventStatus.PLANNED
    )


# ── Автозавершение ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_events_are_planned(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    calendar = await _prepare(uow_factory, FakeVkGateway(admins={ADMIN_VK_ID}))
    added = await calendar.add_event(
        CURATOR_VK_ID,
        EventData(event_date=date(2026, 10, 10), event_type=EventType.GAME),
    )
    result = await calendar.generate_month_trainings(
        CURATOR_VK_ID, MonthPeriod(2026, 10)
    )

    assert added.status is EventStatus.PLANNED
    assert {ev.status for ev in result.created} == {EventStatus.PLANNED}


@pytest.mark.asyncio
async def test_complete_finished_events_marks_only_ended(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    calendar = await _prepare(uow_factory, FakeVkGateway(admins={ADMIN_VK_ID}))
    period = MonthPeriod(2026, 9)
    await calendar.generate_month_trainings(CURATOR_VK_ID, period)

    # Вт 08.09 20:31: Вт 19:00 закончилась в 20:30, Вт 20:30 идёт до 22:00.
    async with uow_factory() as uow:
        completed = await complete_finished_events(
            uow, datetime(2026, 9, 8, 20, 31)
        )
        await uow.commit()

    # 01.09 ×2, 03.09, 04.09, 08.09 19:00.
    assert completed == 5
    done = await calendar.list_month(period, status=EventStatus.DONE)
    assert (done[-1].event_date, done[-1].event_time) == (
        date(2026, 9, 8),
        time(19, 0),
    )

    # Повторный проход в тот же момент ничего не меняет.
    async with uow_factory() as uow:
        assert (
            await complete_finished_events(uow, datetime(2026, 9, 8, 20, 31))
            == 0
        )


@pytest.mark.asyncio
async def test_complete_finished_events_skips_cancelled(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    calendar = await _prepare(uow_factory, FakeVkGateway(admins={ADMIN_VK_ID}))
    game = await calendar.add_event(
        CURATOR_VK_ID,
        EventData(event_date=date(2026, 10, 10), event_type=EventType.GAME),
    )
    await calendar.cancel_event(CURATOR_VK_ID, game.id)

    async with uow_factory() as uow:
        completed = await complete_finished_events(
            uow, datetime(2026, 10, 12, 0, 0)
        )
        await uow.commit()

    assert completed == 0
    [event] = await calendar.list_month(MonthPeriod(2026, 10))
    assert event.status is EventStatus.CANCELLED


# ── Отмена ───────────────────────────────────────────────────────────────


async def _add_training(calendar: CalendarUseCases) -> CalendarEvent:
    return await calendar.add_event(
        CURATOR_VK_ID,
        EventData(
            event_date=date(2026, 10, 6),
            event_type=EventType.TRAINING,
            event_time=time(19, 0),
        ),
    )


@pytest.mark.asyncio
async def test_cancel_event_hides_it_from_planned_and_logs(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    calendar = await _prepare(uow_factory, FakeVkGateway(admins={ADMIN_VK_ID}))
    event = await _add_training(calendar)

    cancelled = await calendar.cancel_event(CURATOR_VK_ID, event.id)

    assert cancelled.status is EventStatus.CANCELLED
    period = MonthPeriod(2026, 10)
    assert await calendar.list_month(period, status=EventStatus.PLANNED) == []
    async with uow_factory() as uow:
        actions = [entry.action for entry in await uow.action_log.recent()]
    assert 'calendar.cancel' in actions


@pytest.mark.asyncio
async def test_cancel_event_only_planned(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    calendar = await _prepare(uow_factory, FakeVkGateway(admins={ADMIN_VK_ID}))
    event = await _add_training(calendar)
    await calendar.cancel_event(CURATOR_VK_ID, event.id)

    with pytest.raises(ValidationError):
        await calendar.cancel_event(CURATOR_VK_ID, event.id)


@pytest.mark.asyncio
async def test_cancel_event_requires_curator(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    calendar = await _prepare(uow_factory, FakeVkGateway(admins={ADMIN_VK_ID}))
    event = await _add_training(calendar)

    with pytest.raises(PermissionDeniedError):
        await calendar.cancel_event(PLAYER_VK_ID, event.id)


@pytest.mark.asyncio
async def test_generate_does_not_recreate_cancelled_training(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    calendar = await _prepare(uow_factory, FakeVkGateway(admins={ADMIN_VK_ID}))
    period = MonthPeriod(2026, 10)
    first = await calendar.generate_month_trainings(CURATOR_VK_ID, period)
    await calendar.cancel_event(CURATOR_VK_ID, first.created[0].id)

    again = await calendar.generate_month_trainings(CURATOR_VK_ID, period)

    assert again.created == []
    assert again.skipped == len(first.created)


# ── Страница расписания ──────────────────────────────────────────────────


def test_schedule_page_event_has_status() -> None:
    path = Path(__file__).resolve().parent.parent / 'scripts'
    spec = importlib.util.spec_from_file_location(
        'build_schedule_page', path / 'build_schedule_page.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    event = _event(date(2026, 10, 6), time(19, 0))
    event.status = EventStatus.CANCELLED

    assert module.event_to_dict(event)['status'] == 'cancelled'
