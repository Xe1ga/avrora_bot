"""Хендлеры календаря: редактирование куратором (ТЗ 3.7).

Просмотр календаря реализован в ``common.py`` (доступен всем). Управление
(добавление/удаление события) — кнопки раздела «Календарь: управление» с
пошаговым FSM-диалогом, по образцу handlers/one_time.py.
"""

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.adapters.vk.states import CalendarManageState
from avrora_bot.application.services.permissions import has_access
from avrora_bot.application.use_cases.calendar import EventData
from avrora_bot.domain.enums import EventType, RoleName
from avrora_bot.domain.errors import DomainError, ValidationError

_CALENDAR_MANAGE_TEXT = '🗓 Управление календарём — выберите действие:'

_EVENT_TYPE_ALIASES = {
    'тренировка': EventType.TRAINING,
    'тренировки': EventType.TRAINING,
    'training': EventType.TRAINING,
    'игра': EventType.GAME,
    'game': EventType.GAME,
}


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры редактирования календаря."""
    dispenser = bot.state_dispenser

    async def _is_curator(vk_id: int) -> bool:
        roles = await ctx.user_management.effective_roles(vk_id)
        return has_access(roles, RoleName.CURATOR)

    @bot.on.message(payload={'cmd': 'calendar_help'})
    async def calendar_help(message: Message) -> None:
        if not await _is_curator(message.from_id):
            await message.answer('⚠️ Команда доступна только куратору.')
            return
        await message.answer(
            _CALENDAR_MANAGE_TEXT, keyboard=keyboards.calendar_actions()
        )

    @bot.on.message(payload={'cmd': 'calendar_add'})
    async def start_add_event(message: Message) -> None:
        if not await _is_curator(message.from_id):
            await message.answer('⚠️ Команда доступна только куратору.')
            return
        await dispenser.set(message.peer_id, CalendarManageState.ADD_DATE)
        await message.answer(
            'Введите дату события (ДД.ММ.ГГГГ):',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=CalendarManageState.ADD_DATE)
    async def step_add_date(message: Message) -> None:
        try:
            event_date = helpers.parse_birthdate(message.text)
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПовторите ввод даты:',
                keyboard=keyboards.cancel(),
            )
            return
        await dispenser.set(
            message.peer_id,
            CalendarManageState.ADD_TYPE,
            event_date=event_date,
        )
        await message.answer(
            'Выберите тип события:',
            keyboard=keyboards.calendar_event_type(),
        )

    @bot.on.message(
        payload_contains={'cmd': 'calendar_add_type'},
        state=CalendarManageState.ADD_TYPE,
    )
    async def step_add_type(message: Message) -> None:
        event_type = _EVENT_TYPE_ALIASES.get(_payload_value(message, 'type'))
        if event_type is None:
            return
        peer = await dispenser.get(message.peer_id)
        await dispenser.set(
            message.peer_id,
            CalendarManageState.ADD_TIME,
            **peer.payload,
            event_type=event_type,
        )
        await message.answer(
            'Введите время начала ЧЧ:ММ или «-», если без времени:',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=CalendarManageState.ADD_TIME)
    async def step_add_time(message: Message) -> None:
        try:
            event_time = helpers.parse_event_time(message.text)
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПовторите ввод времени или «-»:',
                keyboard=keyboards.cancel(),
            )
            return
        peer = await dispenser.get(message.peer_id)
        await dispenser.set(
            message.peer_id,
            CalendarManageState.ADD_PLACE,
            **peer.payload,
            event_time=event_time,
        )
        await message.answer(
            'Введите место проведения или «-»:',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=CalendarManageState.ADD_PLACE)
    async def step_add_place(message: Message) -> None:
        peer = await dispenser.get(message.peer_id)
        data = EventData(
            event_date=peer.payload['event_date'],
            event_type=peer.payload['event_type'],
            event_time=peer.payload['event_time'],
            place=helpers.parse_optional(message.text),
        )
        try:
            event = await ctx.calendar.add_event(message.from_id, data)
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПовторите ввод места или «-»:',
                keyboard=keyboards.cancel(),
            )
            return
        await dispenser.delete(message.peer_id)
        await message.answer(
            f'Событие добавлено (id {event.id}): '
            f'{event.event_date.strftime("%d.%m")} '
            f'{event.event_type.value}.'
        )

    @bot.on.message(payload={'cmd': 'calendar_delete'})
    async def start_delete_event(message: Message) -> None:
        if not await _is_curator(message.from_id):
            await message.answer('⚠️ Команда доступна только куратору.')
            return
        await dispenser.set(message.peer_id, CalendarManageState.DELETE_ID)
        await message.answer(
            'Введите id события для удаления:',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=CalendarManageState.DELETE_ID)
    async def step_delete_event(message: Message) -> None:
        raw = message.text.strip()
        if not raw.isdigit():
            await message.answer(
                '⚠️ id — целое число. Повторите ввод:',
                keyboard=keyboards.cancel(),
            )
            return
        event_id = int(raw)
        try:
            await ctx.calendar.delete_event(message.from_id, event_id)
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПовторите ввод id или нажмите «Отмена».',
                keyboard=keyboards.cancel(),
            )
            return
        await dispenser.delete(message.peer_id)
        await message.answer(f'Событие id {event_id} удалено.')


def _payload_value(message: Message, key: str) -> str:
    """Извлекает значение поля из payload инлайн-кнопки."""
    payload = message.get_payload_json() or {}
    return str(payload.get(key, ''))


def _build_event(day: str, etype: str, etime: str, place: str) -> EventData:
    """Собирает ``EventData`` из аргументов текстовой команды (legacy).

    Больше не вызывается из хендлеров (добавление события теперь — диалог
    по кнопке, см. ``step_add_*`` выше), но формат разбора данных совпадает
    с ним — оставлена для справки/возможного переиспользования.
    """
    event_type = _EVENT_TYPE_ALIASES.get(etype.strip().lower())
    if event_type is None:
        raise ValidationError('Тип события: тренировка/игра')
    return EventData(
        event_date=helpers.parse_birthdate(day),
        event_type=event_type,
        event_time=helpers.parse_event_time(etime),
        place=place.strip() or None,
    )
