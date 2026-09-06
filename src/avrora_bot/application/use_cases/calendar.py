"""Use case'ы календаря тренировок и игр (ТЗ 3.7).

Просмотр доступен всем, редактирование — только куратору (и администратору).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, time

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

    async def list_month(self, period: MonthPeriod) -> list[CalendarEvent]:
        """Просмотр событий месяца (доступно всем)."""
        async with self._uow_factory() as uow:
            return await uow.calendar.list_for_month(period)
