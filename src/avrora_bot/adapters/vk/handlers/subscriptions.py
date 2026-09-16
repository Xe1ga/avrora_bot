"""Хендлеры учёта абонементов для сборщика платежей (ТЗ 3.2)."""

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.adapters.vk.states import SubscriptionState
from avrora_bot.application.services.permissions import has_access
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import DomainError

_SUBSCRIPTIONS_HELP_TEXT = (
    '💰 Команды по абонементам:\n\n'
    '• «расчёт <период> <число голосов>» — расчёт суммы на человека\n'
    '  Пример: расчёт 2026-09 12\n'
    '• «голоса <период>» — зафиксировать голосование; бот отдельным '
    'сообщением запросит список vk_id проголосовавших\n'
    '• «сумма <период> <сумма>» — изменить сумму на человека\n'
    '• «добавить голос <период> <vk_id>» — добавить участника в список\n'
    '• «убрать голос <период> <vk_id>» — убрать участника из списка\n'
    '• «оплатил <период> <vk_id>» / «не оплатил <период> <vk_id>» — '
    'отметить оплату'
)


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры абонементов."""
    dispenser = bot.state_dispenser

    @bot.on.message(
        text=['расчёт <period> <voters:int>', 'расчет <period> <voters:int>']
    )
    async def calc(message: Message, period: str, voters: int) -> None:
        try:
            month = helpers.parse_period(period)
            result = await ctx.subscriptions.calculate(
                message.from_id, month, voters
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Расчёт на {month.label()}:\n'
            f'Тренировок: {result.cost.trainings}, '
            f'часов зала: {result.cost.hall_hours}\n'
            f'Зал: {result.cost.hall_sum} ₽, '
            f'тренер: {result.cost.coach_sum} ₽\n'
            f'Итого: {result.cost.total} ₽\n'
            f'На человека ({voters}): {result.per_person_amount} ₽\n\n'
            'Зафиксировать: «голоса <период>» со списком vk_id.'
        )

    @bot.on.message(text=['голоса <period>'])
    async def start_register_voting(message: Message, period: str) -> None:
        # Список vk_id запрашивается отдельным сообщением через FSM, а не
        # новыми строками этого же сообщения — раньше сборщики нередко
        # присылали id вторым сообщением, и бот его молча игнорировал
        # (не было хендлера, ловящего продолжение диалога).
        try:
            helpers.parse_period(period)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not has_access(roles, RoleName.COLLECTOR):
            await message.answer(
                '⚠️ Команда доступна только сборщику платежей.'
            )
            return
        await dispenser.set(
            message.peer_id, SubscriptionState.VOTERS, period=period
        )
        await message.answer(
            'Отправьте список vk_id проголосовавших — каждый с новой '
            'строки или через запятую.',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=SubscriptionState.VOTERS)
    async def finish_register_voting(message: Message) -> None:
        peer = await dispenser.get(message.peer_id)
        period = peer.payload['period']
        try:
            month = helpers.parse_period(period)
            voter_ids = helpers.parse_vk_ids(message.text)
            sub = await ctx.subscriptions.register_voting(
                message.from_id, month, voter_ids
            )
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПришлите список vk_id ещё раз или нажмите '
                '«Отмена».',
                keyboard=keyboards.cancel(),
            )
            return
        await dispenser.delete(message.peer_id)
        await message.answer(
            f'Подписка на {month.label()} создана.\n'
            f'Проголосовало: {sub.voters_count}, '
            f'сумма на человека: {sub.per_person_amount} ₽.\n'
            'Изменить сумму: «сумма <период> <значение>».'
        )

    @bot.on.message(text=['сумма <period> <amount>'])
    async def override_amount(
        message: Message, period: str, amount: str
    ) -> None:
        try:
            month = helpers.parse_period(period)
            value = helpers.parse_amount(amount)
            sub = await ctx.subscriptions.override_amount(
                message.from_id, month, value
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Сумма абонемента на {month.label()}: {sub.per_person_amount} ₽.'
        )

    @bot.on.message(text=['добавить голос <period> <vk_id:int>'])
    async def add_voter(message: Message, period: str, vk_id: int) -> None:
        try:
            month = helpers.parse_period(period)
            sub = await ctx.subscriptions.add_voter(
                message.from_id, month, vk_id
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Добавлено: vk_id {vk_id}.\n'
            f'Проголосовало: {sub.voters_count}, '
            f'сумма на человека: {sub.per_person_amount} ₽.'
        )

    @bot.on.message(text=['убрать голос <period> <vk_id:int>'])
    async def remove_voter(message: Message, period: str, vk_id: int) -> None:
        try:
            month = helpers.parse_period(period)
            sub = await ctx.subscriptions.remove_voter(
                message.from_id, month, vk_id
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Убрано: vk_id {vk_id}.\n'
            f'Проголосовало: {sub.voters_count}, '
            f'сумма на человека: {sub.per_person_amount} ₽.'
        )

    @bot.on.message(text=['оплатил <period> <vk_id:int>'])
    async def mark_paid(message: Message, period: str, vk_id: int) -> None:
        await _mark(ctx, message, period, vk_id, paid=True)

    @bot.on.message(text=['не оплатил <period> <vk_id:int>'])
    async def mark_unpaid(message: Message, period: str, vk_id: int) -> None:
        await _mark(ctx, message, period, vk_id, paid=False)

    @bot.on.message(payload={'cmd': 'subscriptions_help'})
    async def subscriptions_help(message: Message) -> None:
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not has_access(roles, RoleName.COLLECTOR):
            await message.answer('⚠️ Команда доступна только сборщику платежей.')
            return
        await message.answer(_SUBSCRIPTIONS_HELP_TEXT)


async def _mark(
    ctx: BotContext,
    message: Message,
    period: str,
    vk_id: int,
    *,
    paid: bool,
) -> None:
    """Общая логика отметки оплаты."""
    try:
        month = helpers.parse_period(period)
        await ctx.subscriptions.mark_payment(
            message.from_id, month, vk_id, paid
        )
    except DomainError as exc:
        await message.answer(f'⚠️ {exc}')
        return
    mark = 'оплачено ✅' if paid else 'не оплачено ❌'
    await message.answer(f'Отмечено: vk_id {vk_id} — {mark}.')
