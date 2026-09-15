"""Хендлеры администратора: заявки, добавление, роли."""

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.states import AdminState
from avrora_bot.application.services.permissions import has_access
from avrora_bot.application.use_cases.registration import RegistrationData
from avrora_bot.domain.enums import RoleName, UserStatus
from avrora_bot.domain.errors import DomainError

_ADMIN_HELP_TEXT = (
    '🛠 Команды администратора:\n\n'
    '• «добавить <vk_id> <роль> <ФИО>» — добавить пользователя вручную\n'
    '  Пример: добавить 12345 игрок Иван Иванов\n'
    '• «роль <vk_id> <роль>» — назначить роль\n'
    '• «снять роль <vk_id> <роль>» — снять роль\n'
    '• «удалить пользователя <vk_id>» — уничтожить персональные данные\n'
    '  (ФИО/телефон/ДР/рост) по отзыву согласия, ст. 21 152-ФЗ\n\n'
    'Роли: админ/сборщик/куратор/игрок.'
)

# Текст, которым администратор подтверждает уничтожение персональных
# данных — явное действие, а не случайное нажатие/опечатка (ст. 9 152-ФЗ:
# согласие/отзыв должны быть однозначным действием субъекта или, здесь,
# сознательным решением оператора по его запросу).
_DELETE_CONFIRM_PHRASE = 'ПОДТВЕРЖДАЮ'

# Соответствие текстовых имён ролей значениям enum (для команд).
_ROLE_ALIASES = {
    'админ': RoleName.ADMIN,
    'admin': RoleName.ADMIN,
    'сборщик': RoleName.COLLECTOR,
    'collector': RoleName.COLLECTOR,
    'куратор': RoleName.CURATOR,
    'curator': RoleName.CURATOR,
    'игрок': RoleName.PLAYER,
    'player': RoleName.PLAYER,
}


def _parse_role(raw: str) -> RoleName | None:
    return _ROLE_ALIASES.get(raw.strip().lower())


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры администратора."""
    dispenser = bot.state_dispenser

    @bot.on.message(payload={'cmd': 'requests'})
    @bot.on.message(text=['заявки'])
    async def list_pending(message: Message) -> None:
        try:
            pending = await ctx.registration.list_pending(message.from_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        if not pending:
            await message.answer('Новых заявок нет.')
            return
        await message.answer(f'Заявок на подтверждение: {len(pending)}')
        for user in pending:
            await message.answer(
                f'👤 {user.full_name} (vk_id {user.vk_id})',
                keyboard=keyboards.approve_reject(user.vk_id),
            )

    @bot.on.message(payload_contains={'cmd': 'approve'})
    async def approve(message: Message) -> None:
        vk_id = _payload_vk_id(message)
        try:
            user = await ctx.registration.approve(message.from_id, vk_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(f'✅ {user.full_name} подтверждён.')

    @bot.on.message(payload_contains={'cmd': 'reject'})
    async def reject(message: Message) -> None:
        vk_id = _payload_vk_id(message)
        try:
            user = await ctx.registration.reject(message.from_id, vk_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(f'❌ Заявка {user.full_name} отклонена.')

    @bot.on.message(text=['добавить <vk_id:int> <role> <full_name>'])
    async def add_user(
        message: Message, vk_id: int, role: str, full_name: str
    ) -> None:
        role_enum = _parse_role(role)
        if role_enum is None:
            await message.answer(
                'Роль: админ/сборщик/куратор/игрок. '
                'Пример: добавить 12345 игрок Иван Иванов'
            )
            return
        try:
            await ctx.registration.admin_add_user(
                message.from_id,
                RegistrationData(vk_id=vk_id, full_name=full_name),
                role_enum,
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Добавлен {full_name} (vk_id {vk_id}) с ролью {role_enum.value}.'
        )

    @bot.on.message(text=['роль <vk_id:int> <role>'])
    async def assign_role(message: Message, vk_id: int, role: str) -> None:
        role_enum = _parse_role(role)
        if role_enum is None:
            await message.answer('Неизвестная роль.')
            return
        try:
            await ctx.roles.assign_role(message.from_id, vk_id, role_enum)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(f'Роль {role_enum.value} назначена vk_id {vk_id}.')

    @bot.on.message(text=['снять роль <vk_id:int> <role>'])
    async def revoke_role(message: Message, vk_id: int, role: str) -> None:
        role_enum = _parse_role(role)
        if role_enum is None:
            await message.answer('Неизвестная роль.')
            return
        try:
            await ctx.roles.revoke_role(message.from_id, vk_id, role_enum)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(f'Роль {role_enum.value} снята с vk_id {vk_id}.')

    @bot.on.message(text=['удалить пользователя <vk_id:int>'])
    async def start_delete_user(message: Message, vk_id: int) -> None:
        try:
            user = await ctx.user_management.get_user(message.from_id, vk_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        if user.status is UserStatus.DELETED:
            await message.answer(
                'Персональные данные этого пользователя уже удалены.'
            )
            return
        roles = ', '.join(sorted(role.value for role in user.roles)) or '—'
        await dispenser.set(
            message.peer_id, AdminState.CONFIRM_DELETE_USER, vk_id=vk_id
        )
        await message.answer(
            f'{user.full_name} (роли: {roles}).\n\n'
            'Это необратимо: ФИО, телефон, дата рождения и рост будут '
            'уничтожены, роли сняты. История оплат/посещений и запись о '
            'согласии останутся — как доказательство правомерности прошлой '
            'обработки и факта отзыва (ст. 21 152-ФЗ).\n\n'
            f'Напишите {_DELETE_CONFIRM_PHRASE} для подтверждения — любой '
            'другой текст отменит удаление.'
        )

    @bot.on.message(state=AdminState.CONFIRM_DELETE_USER)
    async def confirm_delete_user(message: Message) -> None:
        peer = await dispenser.get(message.peer_id)
        vk_id = peer.payload['vk_id']
        await dispenser.delete(message.peer_id)
        if message.text.strip().upper() != _DELETE_CONFIRM_PHRASE:
            await message.answer('Удаление отменено.')
            return
        try:
            await ctx.user_management.delete_personal_data(
                message.from_id, vk_id
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Готово. Персональные данные пользователя (vk_id {vk_id}) удалены.'
        )

    @bot.on.message(payload={'cmd': 'admin_help'})
    async def admin_help(message: Message) -> None:
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not has_access(roles, RoleName.ADMIN):
            await message.answer('⚠️ Команда доступна только администратору.')
            return
        await message.answer(_ADMIN_HELP_TEXT)


def _payload_vk_id(message: Message) -> int:
    """Извлекает vk_id из payload инлайн-кнопки."""
    payload = message.get_payload_json() or {}
    return int(payload.get('vk_id', 0))
