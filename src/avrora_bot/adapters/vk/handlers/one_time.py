"""Хендлеры разовых посещений и тарифа (ТЗ 3.2 п.4)."""

from datetime import UTC, date, datetime

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.application.services.permissions import has_access
from avrora_bot.domain.enums import RoleName, TariffKind
from avrora_bot.domain.errors import DomainError

_ONE_TIME_HELP_TEXT = (
    '🎫 Разовые посещения:\n\n'
    '• «разовый тариф <сумма>» — изменить тариф разового посещения\n'
    '• «разовое <vk_id> [дата]» — зарегистрировать посещение\n'
    '  Дата ДД.ММ.ГГГГ, по умолчанию — сегодня\n'
    '• «разовые <период>» — список посещений за месяц\n'
    '• «разовое оплатил <id>» — отметить оплату посещения'
)


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры разовых посещений."""

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

    @bot.on.message(text=['разовое <vk_id:int>'])
    async def register_visit_today(message: Message, vk_id: int) -> None:
        await _register_visit(ctx, message, vk_id, datetime.now(UTC).date())

    @bot.on.message(text=['разовое <vk_id:int> <day>'])
    async def register_visit_day(
        message: Message, vk_id: int, day: str
    ) -> None:
        try:
            visit_date = _parse_date(day)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _register_visit(ctx, message, vk_id, visit_date)

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
                f'({row.visit.amount} ₽) [id {row.visit.id}]'
            )
        await message.answer('\n'.join(lines))

    @bot.on.message(text=['разовое оплатил <visit_id:int>'])
    async def mark_visit_paid(message: Message, visit_id: int) -> None:
        try:
            await ctx.one_time.mark_paid(message.from_id, visit_id, True)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(f'Разовое посещение id {visit_id}: оплачено ✅.')

    @bot.on.message(payload={'cmd': 'one_time_help'})
    async def one_time_help(message: Message) -> None:
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not has_access(roles, RoleName.COLLECTOR):
            await message.answer('⚠️ Команда доступна только сборщику платежей.')
            return
        await message.answer(_ONE_TIME_HELP_TEXT)


async def _register_visit(
    ctx: BotContext, message: Message, vk_id: int, visit_date: date
) -> None:
    """Общая логика регистрации визита."""
    try:
        visit = await ctx.one_time.register_visit(
            message.from_id, vk_id, visit_date
        )
    except DomainError as exc:
        await message.answer(f'⚠️ {exc}')
        return
    await message.answer(
        f'Разовое посещение зарегистрировано (id {visit.id}, '
        f'{visit.amount} ₽). Отметить оплату: '
        f'«разовое оплатил {visit.id}».'
    )


def _parse_date(raw: str) -> date:
    """Разбирает дату ДД.ММ.ГГГГ (переиспользует парсер ДР)."""
    return helpers.parse_birthdate(raw)
