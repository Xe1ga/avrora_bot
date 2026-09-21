"""Хендлеры учёта абонементов для сборщика платежей (ТЗ 3.2)."""

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.adapters.vk.states import SubscriptionState
from avrora_bot.application.services.permissions import has_access
from avrora_bot.application.services.user_lookup import vk_id_label
from avrora_bot.domain.enums import PaymentStatus, RoleName
from avrora_bot.domain.errors import DomainError

_SUBSCRIPTIONS_HELP_TEXT = (
    '💰 Команды по абонементам:\n\n'
    '• «расчёт <период> <число голосов>» — расчёт суммы на человека\n'
    '  Пример: расчёт 2026-09 12\n'
    '• «голоса <период>» — зафиксировать голосование; бот отдельным '
    'сообщением запросит список vk_id/ФИО проголосовавших\n'
    '• «абонемент <период> <сумма>» — зафиксировать фактическую '
    'цену абонемента\n'
    '• «добавить голос <период> <vk_id или ФИО>» — добавить участника '
    'в список\n'
    '• «убрать голос <период> <vk_id или ФИО>» — убрать участника из '
    'списка\n'
    '• «оплатил <период> <vk_id или ФИО>» / «не оплатил <период> '
    '<vk_id или ФИО>» — отметить оплату\n'
    '• «абонементы <период>» — список участников за месяц: оплатил/не '
    'оплатил, кто собрал\n\n'
    'Вместо vk_id можно указать фамилию, «Фамилия Имя» или полное ФИО — '
    'если совпадений несколько, бот покажет список для уточнения.'
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
            'Зафиксировать: «голоса <период>» со списком vk_id/ФИО.'
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
            'Отправьте список проголосовавших — vk_id или ФИО, каждый с '
            'новой строки или через запятую.',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=SubscriptionState.VOTERS)
    async def finish_register_voting(message: Message) -> None:
        peer = await dispenser.get(message.peer_id)
        period = peer.payload['period']
        try:
            month = helpers.parse_period(period)
            targets = helpers.parse_targets(message.text)
            sub = await ctx.subscriptions.register_voting(
                message.from_id, month, targets
            )
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПришлите список vk_id/ФИО ещё раз или нажмите '
                '«Отмена».',
                keyboard=keyboards.cancel(),
            )
            return
        await dispenser.delete(message.peer_id)
        await message.answer(
            f'Подписка на {month.label()} создана.\n'
            f'Проголосовало: {sub.voters_count}, '
            f'сумма на человека: {sub.per_person_amount} ₽.\n'
            'Зафиксировать факт. цену: «абонемент <период> <значение>».'
        )

    @bot.on.message(text=['абонемент <period> <amount>'])
    async def set_fact_amount(
        message: Message, period: str, amount: str
    ) -> None:
        try:
            month = helpers.parse_period(period)
            value = helpers.parse_amount(amount)
            sub = await ctx.subscriptions.set_fact_amount(
                message.from_id, month, value
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Факт. цена абонемента на {month.label()}: '
            f'{sub.per_percent_amount_fact} ₽.'
        )

    @bot.on.message(text=['добавить голос <period> <target>'])
    async def add_voter(message: Message, period: str, target: str) -> None:
        try:
            month = helpers.parse_period(period)
            change = await ctx.subscriptions.add_voter(
                message.from_id, month, target
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Добавлено: {change.user.full_name} '
            f'({vk_id_label(change.user.vk_id)}).\n'
            f'Проголосовало: {change.subscription.voters_count}, '
            f'сумма на человека: {change.subscription.per_person_amount} ₽.'
        )

    @bot.on.message(text=['убрать голос <period> <target>'])
    async def remove_voter(message: Message, period: str, target: str) -> None:
        try:
            month = helpers.parse_period(period)
            change = await ctx.subscriptions.remove_voter(
                message.from_id, month, target
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Убрано: {change.user.full_name} '
            f'({vk_id_label(change.user.vk_id)}).\n'
            f'Проголосовало: {change.subscription.voters_count}, '
            f'сумма на человека: {change.subscription.per_person_amount} ₽.'
        )

    @bot.on.message(text=['оплатил <period> <target>'])
    async def mark_paid(message: Message, period: str, target: str) -> None:
        await _mark(ctx, message, period, target, paid=True)

    @bot.on.message(text=['не оплатил <period> <target>'])
    async def mark_unpaid(message: Message, period: str, target: str) -> None:
        await _mark(ctx, message, period, target, paid=False)

    @bot.on.message(text=['абонементы <period>'])
    async def list_payments(message: Message, period: str) -> None:
        try:
            month = helpers.parse_period(period)
            summary = await ctx.subscriptions.month_summary(month)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        lines = [f'Абонементы за {month.label()}:', '']
        for row in summary.rows:
            mark = '✅' if row.status is PaymentStatus.PAID else '❌'
            line = f'{mark} {row.user.full_name}'
            if row.collector_name is not None:
                line += f' — собрал: {row.collector_name}'
            lines.append(line)
        lines.append('')
        lines.extend(
            [
                f'Сумма абонемента: {summary.subscription.effective_amount} ₽',
                f'Оплатили: {summary.paid_count} из {len(summary.rows)}',
                f'Собрано: {summary.collected} ₽',
            ]
        )
        await message.answer('\n'.join(lines))

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
    target: str,
    *,
    paid: bool,
) -> None:
    """Общая логика отметки оплаты."""
    try:
        month = helpers.parse_period(period)
        user = await ctx.subscriptions.mark_payment(
            message.from_id, month, target, paid
        )
    except DomainError as exc:
        await message.answer(f'⚠️ {exc}')
        return
    mark = 'оплачено ✅' if paid else 'не оплачено ❌'
    await message.answer(
        f'Отмечено: {user.full_name} '
        f'({vk_id_label(user.vk_id)}) — {mark}.'
    )
