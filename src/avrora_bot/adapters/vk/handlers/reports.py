"""Хендлеры отчётов: краткая сводка, XLSX по абонементам, сводная книга.

XLSX-отчёты повторяют вкладки ручной таблицы клуба (``tmp/avrora.xlsx``),
см. ``adapters/reports``. Все отчёты — только для сборщика и админа: в них
ФИО участников и суммы.
"""

from pathlib import Path

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.reports.finance_xlsx import build_finance_workbook
from avrora_bot.adapters.reports.subscription_xlsx import (
    build_subscription_report,
)
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.gateway import VkbottleGateway
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.application.services.permissions import has_access
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import DomainError, NotFoundError

_ONLY_COLLECTOR = '⚠️ Команда доступна только сборщику платежей.'

_REPORTS_HELP_TEXT = (
    '📊 Отчёты за месяц:\n\n'
    '• «сводка <период>» / «отчёт <период>» — краткая сводка по '
    'абонементам в чат\n'
    '• «xlsx <период>» / «файл <период>» — абонементы файлом, как вкладка '
    '«абонемент» таблицы клуба: итого, цель, недобор, кто сколько собрал\n'
    '• «разовые отчёт <период>» — разовые посещения файлом\n'
    '• «расходы отчёт <период>» — расходы файлом\n'
    '• «остаток отчёт [ДД.ММ.ГГГГ]» — остатки на дату файлом\n'
    '• «финансы <период>» — всё сразу одной книгой: абонемент, разовая, '
    'расходы, остаток на конец месяца (для текущего месяца — на сегодня)\n\n'
    'Пример: финансы 2026-09'
)


def register(
    bot: Bot,
    ctx: BotContext,
    gateway: VkbottleGateway,
    report_dir: Path,
) -> None:
    """Регистрирует хендлеры отчётов."""

    async def _is_collector(vk_id: int) -> bool:
        roles = await ctx.user_management.effective_roles(vk_id)
        return has_access(roles, RoleName.COLLECTOR)

    @bot.on.message(
        text=['сводка <period>', 'отчёт <period>', 'отчет <period>']
    )
    async def text_summary(message: Message, period: str) -> None:
        if not await _is_collector(message.from_id):
            await message.answer(_ONLY_COLLECTOR)
            return
        try:
            month = helpers.parse_period(period)
            text = await ctx.reports.text_summary(month)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(text)

    @bot.on.message(text=['xlsx <period>', 'файл <period>', 'excel <period>'])
    async def xlsx_report(message: Message, period: str) -> None:
        if not await _is_collector(message.from_id):
            await message.answer(_ONLY_COLLECTOR)
            return
        try:
            month = helpers.parse_period(period)
            summary = await ctx.subscriptions.month_summary(month)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        out_path = report_dir / f'subscription_{month}.xlsx'
        build_subscription_report(month, summary, out_path)
        await gateway.send_document(
            peer_id=message.peer_id,
            file_path=str(out_path),
            message=f'Абонементы за {month.label()}',
        )

    @bot.on.message(text=['финансы <period>'])
    async def finance_workbook(message: Message, period: str) -> None:
        actor = message.from_id
        try:
            month = helpers.parse_period(period)
            # Остаток — на конец месяца; для текущего месяца — на сегодня.
            end = min(month.last_day, ctx.clock.today())
            if end < month.first_day:
                end = month.last_day
            balances = await ctx.balances.balances(
                actor, end, start=month.first_day
            )
            visits = await ctx.one_time.month_visits(actor, month)
            expenses = await ctx.finance.month_expenses(actor, month)
            try:
                summary = await ctx.subscriptions.month_summary(month)
            except NotFoundError:
                summary = None
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        out_path = report_dir / f'finance_{month}.xlsx'
        build_finance_workbook(
            month, summary, visits, expenses, balances, out_path
        )
        await gateway.send_document(
            peer_id=message.peer_id,
            file_path=str(out_path),
            message=f'Финансы за {month.label()}',
        )

    @bot.on.message(payload={'cmd': 'reports_help'})
    async def reports_help(message: Message) -> None:
        if not await _is_collector(message.from_id):
            await message.answer(_ONLY_COLLECTOR)
            return
        await message.answer(_REPORTS_HELP_TEXT)
