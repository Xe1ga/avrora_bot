"""Хендлер общего списка игроков (админ/сборщик/куратор, ТЗ 2)."""

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.application.services.permissions import has_access
from avrora_bot.application.services.user_lookup import vk_id_label
from avrora_bot.domain.entities import User
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import DomainError

# VK режет длинные сообщения — большой список разбивается на пачки.
_CHUNK_SIZE = 30


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлер списка игроков."""

    @bot.on.message(payload={'cmd': 'players_list'})
    @bot.on.message(text=['список игроков'])
    async def players_list(message: Message) -> None:
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not (
            has_access(roles, RoleName.COLLECTOR)
            or has_access(roles, RoleName.CURATOR)
        ):
            await message.answer(
                '⚠️ Команда доступна администратору, сборщику и куратору.'
            )
            return
        try:
            players = await ctx.user_management.list_players(message.from_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        if not players:
            await message.answer('Игроков пока нет.')
            return
        await message.answer(f'👥 Игроков: {len(players)}')
        for start in range(0, len(players), _CHUNK_SIZE):
            chunk = players[start : start + _CHUNK_SIZE]
            await message.answer(
                '\n\n'.join(_format_player(p) for p in chunk)
            )


def _format_player(user: User) -> str:
    """Одна карточка игрока: ФИО, ДР, рост, телефон, vk_id, роли."""
    height = f'{user.height_cm} см' if user.height_cm is not None else '—'
    birthdate = (
        user.birthdate.strftime('%d.%m.%Y') if user.birthdate else '—'
    )
    phone = user.phone or '—'
    # Как и в других местах (admin.py, common.py) — отсортированные
    # значения enum через запятую, без отдельных русских подписей.
    roles = ', '.join(sorted(role.value for role in user.roles)) or '—'
    return (
        f'👤 {user.full_name}\n'
        f'ДР: {birthdate}\n'
        f'Рост: {height}\n'
        f'Телефон: {phone}\n'
        f'{vk_id_label(user.vk_id)}\n'
        f'Роли: {roles}'
    )
