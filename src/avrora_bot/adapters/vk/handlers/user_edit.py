"""FSM редактирования данных пользователя администратором.

Точка входа — кнопка «✏️ Редактировать пользователя» в главном меню,
которая показывается только администратору (см. ``keyboards.main_menu``).
Видимость кнопки — лишь UI-удобство: доступ всё равно проверяется в
``ctx.user_management`` при каждом шаге, поэтому прямой ввод команды
(в обход кнопки) недоступен так же, как и всем остальным хендлерам админа.
"""

from datetime import date

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.adapters.vk.states import UserEditState
from avrora_bot.domain.entities import User
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import DomainError, PermissionDeniedError

# Поле → (подсказка с текущим значением, состояние для ввода нового).
_FIELD_PROMPTS: dict[str, tuple[str, str]] = {
    'full_name': (
        'Текущее ФИО: {value}\nВведите новое ФИО:',
        UserEditState.FULL_NAME,
    ),
    'phone': (
        'Текущий телефон: {value}\n'
        'Введите новый телефон (или «-», чтобы очистить):',
        UserEditState.PHONE,
    ),
    'birthdate': (
        'Текущая дата рождения: {value}\n'
        'Введите новую дату (ДД.ММ.ГГГГ) или «-», чтобы очистить:',
        UserEditState.BIRTHDATE,
    ),
    'height': (
        'Текущий рост: {value}\n'
        'Введите новый рост (см) или «-», чтобы очистить:',
        UserEditState.HEIGHT,
    ),
}


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры редактирования пользователя."""
    dispenser = bot.state_dispenser

    async def _current_state(peer_id: int) -> str | None:
        peer = await dispenser.get(peer_id)
        if peer is None:
            return None
        state = peer.state
        return (
            state if isinstance(state, str) else getattr(state, 'state', None)
        )

    async def _menu_keyboard(vk_id: int) -> str:
        roles = await ctx.user_management.effective_roles(vk_id)
        return keyboards.main_menu(roles=roles)

    async def _show_fields(message: Message, user: User) -> None:
        await dispenser.set(
            message.peer_id,
            UserEditState.SELECT_FIELD,
            target_vk_id=user.vk_id,
            full_name=user.full_name,
            phone=user.phone,
            birthdate=user.birthdate,
            height=user.height_cm,
        )
        await message.answer(
            _format_profile(user), keyboard=keyboards.edit_user_fields()
        )

    async def _apply(message: Message, value: object, setter) -> None:
        peer = await dispenser.get(message.peer_id)
        target_vk_id = peer.payload['target_vk_id']
        try:
            user = await setter(message.from_id, target_vk_id, value)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _show_fields(message, user)

    @bot.on.message(payload={'cmd': 'edit_user'})
    @bot.on.message(text=['редактировать пользователя'])
    async def start_edit(message: Message) -> None:
        roles = await ctx.user_management.effective_roles(message.from_id)
        if RoleName.ADMIN not in roles:
            await message.answer('⚠️ Требуются права администратора')
            return
        await dispenser.set(message.peer_id, UserEditState.SELECT_USER)
        await message.answer(
            'Введите vk_id пользователя для редактирования:',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=UserEditState.SELECT_USER)
    async def select_user(message: Message) -> None:
        try:
            target_vk_id = int(message.text.strip())
        except ValueError:
            await message.answer('vk_id — целое число. Повторите ввод:')
            return
        try:
            user = await ctx.user_management.get_user(
                message.from_id, target_vk_id
            )
        except PermissionDeniedError as exc:
            await dispenser.delete(message.peer_id)
            await message.answer(
                f'⚠️ {exc}', keyboard=await _menu_keyboard(message.from_id)
            )
            return
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}\nПовторите ввод vk_id:')
            return
        await _show_fields(message, user)

    @bot.on.message(
        payload_contains={'cmd': 'edit_field'},
        state=UserEditState.SELECT_FIELD,
    )
    async def select_field(message: Message) -> None:
        field = _payload_field(message)
        prompt = _FIELD_PROMPTS.get(field)
        if prompt is None:
            return
        peer = await dispenser.get(message.peer_id)
        template, state = prompt
        current = peer.payload.get(field)
        await dispenser.set(message.peer_id, state, **peer.payload)
        await message.answer(
            template.format(value=_display(current)),
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=UserEditState.FULL_NAME)
    async def step_full_name(message: Message) -> None:
        full_name = message.text.strip()
        if len(full_name) < 3:  # noqa: PLR2004
            await message.answer('Слишком короткое имя. Повторите ввод ФИО:')
            return
        await _apply(message, full_name, ctx.user_management.set_full_name)

    @bot.on.message(state=UserEditState.PHONE)
    async def step_phone(message: Message) -> None:
        phone = helpers.parse_optional(message.text)
        await _apply(message, phone, ctx.user_management.set_phone)

    @bot.on.message(state=UserEditState.BIRTHDATE)
    async def step_birthdate(message: Message) -> None:
        try:
            birthdate = helpers.parse_optional_birthdate(message.text)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}\nПовторите ввод даты рождения:')
            return
        await _apply(message, birthdate, ctx.user_management.set_birthdate)

    @bot.on.message(state=UserEditState.HEIGHT)
    async def step_height(message: Message) -> None:
        try:
            height = helpers.parse_optional_height(message.text)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}\nПовторите ввод роста:')
            return
        await _apply(message, height, ctx.user_management.set_height)

    @bot.on.message(payload={'cmd': 'edit_done'})
    async def finish_edit(message: Message) -> None:
        # Сравниваем через `==`, а не `!=`: `StatePeer.state` — это
        # `StateRepresentation` (str), у которого переопределён `__eq__`
        # для сравнения с `BaseStateGroup`, но не `__ne__` — из-за этого
        # `!=` всегда возвращает True (сравнение как обычных строк) и
        # проверка ниже отсекала бы все вызовы, включая корректные.
        if (
            not await _current_state(message.peer_id)  # noqa: SIM201
            == UserEditState.SELECT_FIELD
        ):
            return
        await dispenser.delete(message.peer_id)
        await message.answer(
            'Изменения сохранены.',
            keyboard=await _menu_keyboard(message.from_id),
        )


def _payload_field(message: Message) -> str:
    """Извлекает выбранное поле из payload инлайн-кнопки."""
    payload = message.get_payload_json() or {}
    return str(payload.get('field', ''))


def _display(value: object) -> str:
    """Форматирует значение поля для показа администратору."""
    if value is None:
        return '—'
    if isinstance(value, date):
        return value.strftime('%d.%m.%Y')
    return str(value)


def _format_profile(user: User) -> str:
    """Текущие данные профиля + приглашение выбрать поле для правки."""
    height = f'{user.height_cm} см' if user.height_cm is not None else '—'
    lines = [
        f'👤 Профиль vk_id {user.vk_id}',
        f'ФИО: {user.full_name}',
        f'Телефон: {_display(user.phone)}',
        f'Дата рождения: {_display(user.birthdate)}',
        f'Рост: {height}',
        '',
        'Выберите, что изменить:',
    ]
    return '\n'.join(lines)
