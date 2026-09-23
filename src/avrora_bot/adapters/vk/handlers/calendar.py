"""Хендлеры календаря: редактирование куратором (ТЗ 3.7).

Просмотр календаря реализован в ``common.py`` (доступен всем).
"""

from datetime import UTC, datetime

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.application.services.permissions import has_access
from avrora_bot.application.use_cases.calendar import EventData
from avrora_bot.domain.enums import EventType, RoleName
from avrora_bot.domain.errors import DomainError, ValidationError
from avrora_bot.domain.value_objects import MonthPeriod

_CALENDAR_HELP_TEXT = (
    '🗓 Управление календарём:\n\n'
    '• «событие <дата> <тип> <время> <место>» — добавить событие\n'
    '  Тип: тренировка/игра. Время ЧЧ:ММ, а если не задано — '
    'обязательно поставьте «-» вместо него (иначе место попадёт не в то поле).\n'
    '  Пример с временем: событие 15.09.2026 тренировка 19:00 Зал №1\n'
    '  Пример без времени: событие 20.09.2026 игра - Стадион\n'
    '• «удалить событие <id>» — удалить событие'
)

_EVENT_TYPE_ALIASES = {
    'тренировка': EventType.TRAINING,
    'тренировки': EventType.TRAINING,
    'training': EventType.TRAINING,
    'игра': EventType.GAME,
    'game': EventType.GAME,
}


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры редактирования календаря."""

    @bot.on.message(text=['событие <day> <etype> <etime> <place>'])
    async def add_event(
        message: Message,
        day: str,
        etype: str,
        etime: str,
        place: str,
    ) -> None:
        try:
            data = _build_event(day, etype, etime, place)
            event = await ctx.calendar.add_event(message.from_id, data)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Событие добавлено (id {event.id}): '
            f'{event.event_date.strftime("%d.%m")} '
            f'{event.event_type.value}.'
        )

    @bot.on.message(text=['удалить событие <event_id:int>'])
    async def delete_event(message: Message, event_id: int) -> None:
        try:
            await ctx.calendar.delete_event(message.from_id, event_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(f'Событие id {event_id} удалено.')

    @bot.on.message(payload={'cmd': 'calendar_help'})
    async def calendar_help(message: Message) -> None:
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not has_access(roles, RoleName.CURATOR):
            await message.answer('⚠️ Команда доступна только куратору.')
            return
        await message.answer(_CALENDAR_HELP_TEXT)

    @bot.on.message(payload={'cmd': 'calendar_generate_trainings'})
    async def generate_trainings(message: Message) -> None:
        next_period = MonthPeriod.from_date(
            datetime.now(UTC).date()
        ).next_month()
        try:
            result = await ctx.calendar.generate_month_trainings(
                message.from_id, next_period
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Тренировки на {next_period.label()}: '
            f'создано {len(result.created)}, уже было {result.skipped}.'
        )


def _build_event(day: str, etype: str, etime: str, place: str) -> EventData:
    """Собирает ``EventData`` из аргументов команды."""
    event_type = _EVENT_TYPE_ALIASES.get(etype.strip().lower())
    if event_type is None:
        raise ValidationError('Тип события: тренировка/игра')
    return EventData(
        event_date=helpers.parse_birthdate(day),
        event_type=event_type,
        event_time=helpers.parse_event_time(etime),
        place=place.strip() or None,
    )
