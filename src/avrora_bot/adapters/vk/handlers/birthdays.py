"""Хендлеры раздела «Дни рождения» (поздравитель/администратор, ТЗ 3.4).

Кнопки раздела: «Подписаться» и «Отписаться» спрашивают список vk_id/ФИО
отдельным сообщением (FSM, по образцу handlers/one_time.py), «Список
отслеживаемых» показывает свой список с ближайшими датами. Сами
напоминания рассылает фоновая задача — см. ``app.py``.
"""

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.adapters.vk.states import BirthdayState
from avrora_bot.application.services.permissions import has_access
from avrora_bot.application.use_cases.birthdays import (
    SubscribeResult,
    TrackedBirthday,
    days_left_label,
)
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import DomainError

_BIRTHDAYS_TEXT = (
    '🎂 Дни рождения — выберите действие.\n\n'
    'По своему списку отслеживаемых вы получите напоминание за 10 дней до '
    'дня рождения, в сам день рождения, а в последний день месяца — список '
    'именинников следующего месяца.'
)
_DENIED_TEXT = '⚠️ Команда доступна только поздравителю.'


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры раздела «Дни рождения»."""
    dispenser = bot.state_dispenser

    async def _main_menu(vk_id: int) -> str:
        roles = await ctx.user_management.effective_roles(vk_id)
        return keyboards.main_menu(roles=roles)

    async def _is_greeter(vk_id: int) -> bool:
        roles = await ctx.user_management.effective_roles(vk_id)
        return has_access(roles, RoleName.GREETER)

    @bot.on.message(payload={'cmd': 'birthdays_help'})
    @bot.on.message(text=['дни рождения'])
    async def birthdays_help(message: Message) -> None:
        if not await _is_greeter(message.from_id):
            await message.answer(_DENIED_TEXT)
            return
        await message.answer(
            _BIRTHDAYS_TEXT, keyboard=keyboards.birthday_actions()
        )

    @bot.on.message(payload={'cmd': 'birthdays_subscribe'})
    async def start_subscribe(message: Message) -> None:
        if not await _is_greeter(message.from_id):
            await message.answer(_DENIED_TEXT)
            return
        await dispenser.set(message.peer_id, BirthdayState.SUBSCRIBE)
        await message.answer(
            'На кого подписаться? Отправьте список — vk_id или ФИО, каждый '
            'с новой строки или через запятую. Либо нажмите «Подписаться '
            'на всех».',
            keyboard=keyboards.birthday_subscribe_prompt(),
        )

    @bot.on.message(payload={'cmd': 'birthdays_subscribe_all'})
    async def subscribe_all(message: Message) -> None:
        try:
            result = await ctx.birthdays.subscribe_all(message.from_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await dispenser.delete(message.peer_id)
        await message.answer(
            _format_subscribed(result),
            keyboard=await _main_menu(message.from_id),
        )

    @bot.on.message(state=BirthdayState.SUBSCRIBE)
    async def finish_subscribe(message: Message) -> None:
        try:
            targets = helpers.parse_targets(message.text)
            result = await ctx.birthdays.subscribe(message.from_id, targets)
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПришлите список vk_id/ФИО ещё раз или нажмите '
                '«Отмена».',
                keyboard=keyboards.birthday_subscribe_prompt(),
            )
            return
        await dispenser.delete(message.peer_id)
        await message.answer(
            _format_subscribed(result),
            keyboard=await _main_menu(message.from_id),
        )

    @bot.on.message(payload={'cmd': 'birthdays_unsubscribe'})
    async def start_unsubscribe(message: Message) -> None:
        if not await _is_greeter(message.from_id):
            await message.answer(_DENIED_TEXT)
            return
        await dispenser.set(message.peer_id, BirthdayState.UNSUBSCRIBE)
        await message.answer(
            'От кого отписаться? Отправьте фамилии (или ФИО/vk_id) — каждую '
            'с новой строки или через запятую.',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=BirthdayState.UNSUBSCRIBE)
    async def finish_unsubscribe(message: Message) -> None:
        try:
            queries = helpers.parse_targets(message.text)
            removed = await ctx.birthdays.unsubscribe(message.from_id, queries)
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПришлите список ещё раз или нажмите «Отмена».',
                keyboard=keyboards.cancel(),
            )
            return
        await dispenser.delete(message.peer_id)
        lines = [f'Убраны из отслеживаемых ({len(removed)}):', '']
        lines.extend(f'• {user.full_name}' for user in removed)
        await message.answer(
            '\n'.join(lines), keyboard=await _main_menu(message.from_id)
        )

    @bot.on.message(payload={'cmd': 'birthdays_list'})
    async def list_tracked(message: Message) -> None:
        try:
            rows = await ctx.birthdays.list_tracked(
                message.from_id, ctx.clock.today()
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        for part in helpers.split_message(format_tracked(rows)):
            await message.answer(part)


def _format_subscribed(result: SubscribeResult) -> str:
    lines = [f'Подписка оформлена, добавлено: {len(result.added)}.']
    if result.added:
        lines.append('')
        lines.extend(f'• {user.full_name}' for user in result.added)
    if result.already:
        lines.append('')
        lines.append(f'Уже были в списке: {len(result.already)}.')
    if result.without_birthdate:
        names = ', '.join(user.full_name for user in result.without_birthdate)
        lines.append('')
        lines.append(
            f'⚠️ Дата рождения не указана: {names}. Напоминания появятся, '
            'когда администратор её внесёт.'
        )
    return '\n'.join(lines)


def format_tracked(rows: list[TrackedBirthday]) -> str:
    """Текст списка отслеживаемых: дата, срок до дня рождения, ФИО."""
    if not rows:
        return 'Список отслеживаемых пуст. Нажмите «Подписаться».'
    lines = [f'🎂 Отслеживаемые дни рождения ({len(rows)}):', '']
    for row in rows:
        if row.occasion is None:
            lines.append(f'• {row.user.full_name} — дата рождения не указана')
            continue
        lines.append(
            f'• {row.occasion.strftime("%d.%m")} '
            f'({days_left_label(row.days_left)}) — {row.user.full_name}'
        )
    return '\n'.join(lines)
