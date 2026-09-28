"""Хендлеры остатков: у кого сколько денег клуба на руках на дату."""

from datetime import date

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.application.use_cases.balances import BalanceReport, BalanceRow
from avrora_bot.domain.errors import DomainError


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры остатков."""

    async def _send_balances(message: Message, end: date) -> None:
        try:
            report = await ctx.balances.balances(message.from_id, end)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        for part in helpers.split_message(_format_report(report)):
            await message.answer(part)

    @bot.on.message(payload={'cmd': 'balances_chat'})
    @bot.on.message(text=['остаток', 'остатки'])
    async def balances_today(message: Message) -> None:
        await _send_balances(message, ctx.balances.today())

    @bot.on.message(text=['остаток <day>', 'остатки <day>'])
    async def balances_on_day(message: Message, day: str) -> None:
        try:
            end = helpers.parse_birthdate(day)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _send_balances(message, end)

    @bot.on.message(text=['мой счёт', 'мой счет'])
    async def my_balance(message: Message) -> None:
        end = ctx.balances.today()
        try:
            row = await ctx.balances.my_balance(message.from_id, end)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        start = end.replace(day=1)
        await message.answer(
            f'🏦 Ваш счёт на {_day(end)}: '
            f'{helpers.format_money(row.balance.closing)} ₽\n'
            f'{_breakdown(row, start)}'
        )


def _day(value: date) -> str:
    return value.strftime('%d.%m.%Y')


def _breakdown(row: BalanceRow, start: date) -> str:
    """Разбивка остатка: на начало периода и ненулевые движения за период."""
    b = row.balance
    money = helpers.format_money
    parts = [f'на {start.strftime("%d.%m")}: {money(b.opening)}']
    if b.subscriptions:
        parts.append(f'+абонементы {money(b.subscriptions)}')
    if b.one_time:
        parts.append(f'+разовые {money(b.one_time)}')
    if b.expenses:
        parts.append(f'−расходы {money(b.expenses)}')
    if b.transfers:
        sign = '+' if b.transfers > 0 else '−'
        parts.append(f'{sign}передачи {money(abs(b.transfers))}')
    if b.adjustments:
        sign = '+' if b.adjustments > 0 else '−'
        parts.append(f'{sign}корректировки {money(abs(b.adjustments))}')
    return '  ' + ' · '.join(parts)


def _format_report(report: BalanceReport) -> str:
    lines = [
        f'🏦 Деньги клуба на руках на {_day(report.end)}',
        f'(движения с {_day(report.start)})',
        '',
    ]
    for row in report.rows:
        lines.append(
            f'{row.name}: {helpers.format_money(row.balance.closing)} ₽'
        )
        lines.append(_breakdown(row, report.start))
    lines.extend(
        ['', f'Итого на руках: {helpers.format_money(report.total)} ₽']
    )
    return '\n'.join(lines)
