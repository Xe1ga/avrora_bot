"""Хендлеры учёта абонементов для сборщика платежей (ТЗ 3.2)."""

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.domain.errors import DomainError, ValidationError


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры абонементов."""

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
    async def register_voting(message: Message, period: str) -> None:
        # Список vk_id ожидается в тексте после команды на новых строках.
        lines = message.text.splitlines()
        body = '\n'.join(lines[1:]) if len(lines) > 1 else ''
        try:
            month = helpers.parse_period(period)
            if not body.strip():
                raise ValidationError(
                    'Добавьте список vk_id проголосовавших '
                    '(каждый с новой строки).'
                )
            voter_ids = helpers.parse_vk_ids(body)
            sub = await ctx.subscriptions.register_voting(
                message.from_id, month, voter_ids
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
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

    @bot.on.message(text=['оплатил <period> <vk_id:int>'])
    async def mark_paid(message: Message, period: str, vk_id: int) -> None:
        await _mark(ctx, message, period, vk_id, paid=True)

    @bot.on.message(text=['не оплатил <period> <vk_id:int>'])
    async def mark_unpaid(message: Message, period: str, vk_id: int) -> None:
        await _mark(ctx, message, period, vk_id, paid=False)


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
