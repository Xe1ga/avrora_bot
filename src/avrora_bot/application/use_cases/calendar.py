"""Use case'ы календаря тренировок и игр (ТЗ 3.7).

Просмотр доступен всем, редактирование — только куратору (и администратору).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, time, timedelta

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.domain.entities import CalendarEvent
from avrora_bot.domain.enums import EventType, RoleName
from avrora_bot.domain.errors import NotFoundError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway
from avrora_bot.domain.value_objects import MonthPeriod

UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class EventData:
    """Данные для создания/редактирования события."""

    event_date: date
    event_type: EventType
    event_time: time | None = None
    place: str | None = None
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class GeneratedTrainings:
    """Результат автогенерации тренировок месяца по недельному расписанию."""

    period: MonthPeriod
    created: list[CalendarEvent]
    skipped: int


class CalendarUseCases:
    """Ведение календаря: добавление/редактирование/удаление/просмотр."""

    def __init__(self, uow_factory: UowFactory, vk_gateway: VkGateway) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway

    async def add_event(
        self, actor_vk_id: int, data: EventData
    ) -> CalendarEvent:
        """Добавляет событие (только куратор/администратор)."""
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.CURATOR
            )
            event = await uow.calendar.add(
                CalendarEvent(
                    event_date=data.event_date,
                    event_time=data.event_time,
                    event_type=data.event_type,
                    place=data.place,
                    comment=data.comment,
                    author_vk_id=actor_vk_id,
                )
            )
            await record_action(
                uow,
                actor_vk_id,
                'calendar.add',
                f'date={data.event_date} type={data.event_type.value}',
            )
            await uow.commit()
            return event

    async def edit_event(
        self, actor_vk_id: int, event_id: int, data: EventData
    ) -> CalendarEvent:
        """Редактирует событие (только куратор/администратор)."""
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.CURATOR
            )
            event = await uow.calendar.get(event_id)
            if event is None:
                raise NotFoundError('Событие не найдено')
            event.event_date = data.event_date
            event.event_time = data.event_time
            event.event_type = data.event_type
            event.place = data.place
            event.comment = data.comment
            await uow.calendar.update(event)
            await record_action(
                uow, actor_vk_id, 'calendar.edit', f'id={event_id}'
            )
            await uow.commit()
            return event

    async def delete_event(self, actor_vk_id: int, event_id: int) -> None:
        """Удаляет событие (только куратор/администратор)."""
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.CURATOR
            )
            event = await uow.calendar.get(event_id)
            if event is None:
                raise NotFoundError('Событие не найдено')
            await uow.calendar.delete(event_id)
            await record_action(
                uow, actor_vk_id, 'calendar.delete', f'id={event_id}'
            )
            await uow.commit()

    async def list_month(
        self, period: MonthPeriod, *, from_date: date | None = None
    ) -> list[CalendarEvent]:
        """Просмотр событий месяца (доступно всем).

        ``from_date`` отфильтровывает события раньше этой даты — команда
        «Календарь» без явного периода показывает только предстоящие
        тренировки/игры (см. handlers/common.py). При явном запросе месяца
        («календарь <период>») не передаётся — там нужен весь месяц,
        включая прошедшее, для просмотра истории.
        """
        async with self._uow_factory() as uow:
            events = await uow.calendar.list_for_month(period)
            if from_date is not None:
                events = [ev for ev in events if ev.event_date >= from_date]
            return events

    async def generate_month_trainings(
        self, actor_vk_id: int, period: MonthPeriod
    ) -> GeneratedTrainings:
        """Создаёт тренировки месяца по недельному расписанию (только куратор).

        Расписание — то же самое, что используется при расчёте стоимости
        абонемента (``domain.services.tariff_calc.month_cost``): активные
        слоты ``ScheduleSlot`` (день недели + время начала/конца), см.
        ``uow.schedule``. Идемпотентно: уже существующая тренировка (тот же
        день + то же время начала) не дублируется, повторный вызов на тот
        же месяц только досоздаёт недостающее — как ``seed_reference_data``
        для тарифов/расписания.
        """
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.CURATOR
            )
            active = [
                slot
                for slot in await uow.schedule.active_slots()
                if slot.active
            ]
            if not active:
                raise NotFoundError('Расписание тренировок не задано')

            existing = await uow.calendar.list_for_month(period)
            existing_pairs = {
                (ev.event_date, ev.event_time)
                for ev in existing
                if ev.event_type is EventType.TRAINING
            }
            by_weekday: dict[int, list] = {}
            for slot in active:
                by_weekday.setdefault(slot.weekday.index, []).append(slot)

            created: list[CalendarEvent] = []
            skipped = 0
            day = period.first_day
            while day <= period.last_day:
                for slot in by_weekday.get(day.weekday(), []):
                    if (day, slot.start) in existing_pairs:
                        skipped += 1
                        continue
                    event = await uow.calendar.add(
                        CalendarEvent(
                            event_date=day,
                            event_time=slot.start,
                            event_type=EventType.TRAINING,
                            place=slot.place,
                            comment=None,
                            author_vk_id=actor_vk_id,
                        )
                    )
                    created.append(event)
                day += timedelta(days=1)

            await record_action(
                uow,
                actor_vk_id,
                'calendar.generate_month_trainings',
                f'{period} created={len(created)} skipped={skipped}',
            )
            await uow.commit()
            return GeneratedTrainings(
                period=period, created=created, skipped=skipped
            )
