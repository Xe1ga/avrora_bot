"""Хендлеры разовых посещений и тарифа (ТЗ 3.2 п.4)."""

from datetime import UTC, date, datetime

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.adapters.vk.states import OneTimeState
from avrora_bot.application.services.permissions import has_access
from avrora_bot.domain.enums import RoleName, TariffKind
from avrora_bot.domain.errors import DomainError

_ONE_TIME_HELP_TEXT = (
    '🎫 Разовые посещения:\n\n'
    '• «разовый тариф <сумма>» — изменить тариф разового посещения\n'
    '• «посетили [дата]» — зафиксировать посещение; бот отдельным '
    'сообщением запросит список vk_id/ФИО посетивших\n'
    '  Дата ДД.ММ.ГГГГ, по умолчанию — сегодня\n'
    '• «разовые <период>» — список посещений за месяц\n'
    '• «разовое оплатил <vk_id или ФИО>» — отметить оплаченным самое '
    'старое неоплаченное посещение участника\n\n'
    'Вместо vk_id можно указать фамилию, «Фамилия Имя» или полное ФИО — '
    'если совпадений несколько, бот покажет список для уточнения.'
)


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры разовых посещений."""
    dispenser = bot.state_dispenser

    async def _start_register_visits(
        message: Message, visit_date: date
    ) -> None:
        """Общий старт FSM сбора списка посетивших на заданную дату."""
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not has_access(roles, RoleName.COLLECTOR):
            await message.answer(
                '⚠️ Команда доступна только сборщику платежей.'
            )
            return
        await dispenser.set(
            message.peer_id, OneTimeState.VISITORS, visit_date=visit_date
        )
        await message.answer(
            f'Дата посещения: {visit_date.strftime("%d.%m.%Y")}.\n'
            'Отправьте список посетивших — vk_id или ФИО, каждый с новой '
            'строки или через запятую.',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(text=['разовый тариф <amount>'])
    async def set_one_time_tariff(message: Message, amount: str) -> None:
        try:
            value = helpers.parse_amount(amount)
            today = datetime.now(UTC).date()
            await ctx.tariffs.set_tariff(
                message.from_id, TariffKind.ONE_TIME, value, today
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Тариф разового посещения: {value} ₽ (с сегодняшнего дня).'
        )

    @bot.on.message(text=['посетили'])
    async def start_register_visits_today(message: Message) -> None:
        await _start_register_visits(message, datetime.now(UTC).date())

    @bot.on.message(text=['посетили <day>'])
    async def start_register_visits_day(message: Message, day: str) -> None:
        try:
            visit_date = _parse_date(day)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _start_register_visits(message, visit_date)

    @bot.on.message(state=OneTimeState.VISITORS)
    async def finish_register_visits(message: Message) -> None:
        # Список vk_id/ФИО запрашивается отдельным сообщением через FSM —
        # по аналогии с «голоса <период>» (см. handlers/subscriptions.py).
        peer = await dispenser.get(message.peer_id)
        visit_date = peer.payload['visit_date']
        try:
            targets = helpers.parse_targets(message.text)
            outcomes = await ctx.one_time.register_visits(
                message.from_id, targets, visit_date
            )
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПришлите список vk_id/ФИО ещё раз или нажмите '
                '«Отмена».',
                keyboard=keyboards.cancel(),
            )
            return
        await dispenser.delete(message.peer_id)
        lines = [
            f'Разовые посещения на {visit_date.strftime("%d.%m.%Y")} '
            f'зарегистрированы ({len(outcomes)}):',
            '',
        ]
        lines.extend(
            f'• {outcome.user.full_name} (vk_id {outcome.user.vk_id}), '
            f'{outcome.visit.amount} ₽'
            for outcome in outcomes
        )
        lines.append('')
        lines.append('Отметить оплату: «разовое оплатил <ФИО>».')
        await message.answer('\n'.join(lines))

    @bot.on.message(text=['разовые <period>'])
    async def list_visits(message: Message, period: str) -> None:
        try:
            month = helpers.parse_period(period)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        rows = await ctx.one_time.month_visits(month)
        if not rows:
            await message.answer(f'Разовых посещений в {month.label()} нет.')
            return
        lines = [f'Разовые посещения за {month.label()}:', '']
        for row in rows:
            mark = '✅' if row.visit.status.value == 'paid' else '❌'
            lines.append(
                f'{mark} {row.full_name} — '
                f'{row.visit.visit_date.strftime("%d.%m")} '
                f'({row.visit.amount} ₽)'
            )
        await message.answer('\n'.join(lines))

    @bot.on.message(text=['разовое оплатил <target>'])
    async def mark_visit_paid(message: Message, target: str) -> None:
        try:
            outcome = await ctx.one_time.mark_oldest_unpaid(
                message.from_id, target
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Разовое посещение {outcome.user.full_name} '
            f'(vk_id {outcome.user.vk_id}): оплачено ✅.'
        )

    @bot.on.message(payload={'cmd': 'one_time_help'})
    async def one_time_help(message: Message) -> None:
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not has_access(roles, RoleName.COLLECTOR):
            await message.answer('⚠️ Команда доступна только сборщику платежей.')
            return
        await message.answer(_ONE_TIME_HELP_TEXT)


def _parse_date(raw: str) -> date:
    """Разбирает дату ДД.ММ.ГГГГ (переиспользует парсер ДР)."""
    return helpers.parse_birthdate(raw)
