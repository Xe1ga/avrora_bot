"""Хендлеры отчётов: краткая сводка и XLSX (ТЗ 3.2 п.6)."""

from pathlib import Path

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.reports.xlsx import build_month_report
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.gateway import VkbottleGateway
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.application.services.permissions import has_access
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import DomainError

_REPORTS_HELP_TEXT = (
    '📊 Отчёты за месяц:\n\n'
    '• «сводка <период>» / «отчёт <период>» — краткая сводка в чат\n'
    '• «xlsx <период>» / «файл <период>» — полный отчёт файлом'
)


def register(
    bot: Bot,
    ctx: BotContext,
    gateway: VkbottleGateway,
    report_dir: Path,
) -> None:
    """Регистрирует хендлеры отчётов."""

    @bot.on.message(
        text=['сводка <period>', 'отчёт <period>', 'отчет <period>']
    )
    async def text_summary(message: Message, period: str) -> None:
        try:
            month = helpers.parse_period(period)
            text = await ctx.reports.text_summary(month)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(text)

    @bot.on.message(text=['xlsx <period>', 'файл <period>', 'excel <period>'])
    async def xlsx_report(message: Message, period: str) -> None:
        try:
            month = helpers.parse_period(period)
            summary = await ctx.subscriptions.month_summary(month)
            hall_sum, coach_sum = await ctx.reports.month_financials(month)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        out_path = report_dir / f'report_{month}.xlsx'
        build_month_report(month, summary, hall_sum, coach_sum, out_path)
        await gateway.send_document(
            peer_id=message.peer_id,
            file_path=str(out_path),
            message=f'Отчёт за {month.label()}',
        )

    @bot.on.message(payload={'cmd': 'reports_help'})
    async def reports_help(message: Message) -> None:
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not has_access(roles, RoleName.COLLECTOR):
            await message.answer('⚠️ Команда доступна только сборщику платежей.')
            return
        await message.answer(_REPORTS_HELP_TEXT)
