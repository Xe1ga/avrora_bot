"""Общие хендлеры: старт, помощь, меню, статус, просмотр календаря."""

from datetime import UTC, date, datetime

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.domain.enums import EventType
from avrora_bot.domain.errors import DomainError
from avrora_bot.domain.value_objects import MonthPeriod

_HELP_TEXT = (
    'Бот волейбольного клуба «Аврора».\n\n'
    'Доступные команды:\n'
    '• «Календарь» — расписание тренировок и игр на месяц\n'
    '• «Мой статус» — ваш профиль и роли\n'
    '• «Регистрация» — подать заявку игрока\n\n'
    'Команды для сборщика/куратора/администратора вводятся текстом, '
    'например: «отчёт 2026-09», «календарь 2026-09».'
)

_EVENT_LABELS = {
    EventType.TRAINING: '🏐 Тренировка',
    EventType.GAME: '🏆 Игра',
}


def register(bot: Bot, ctx: BotContext, *, schedule_url: str) -> None:
    """Регистрирует общие хендлеры."""

    async def _main_menu(vk_id: int) -> str:
        roles = await ctx.user_management.effective_roles(vk_id)
        return keyboards.main_menu(roles=roles)

    @bot.on.message(payload={'cmd': 'help'})
    @bot.on.message(text=['помощь', 'help', '/help'])
    async def help_handler(message: Message) -> None:
        await message.answer(
            _HELP_TEXT, keyboard=await _main_menu(message.from_id)
        )

    @bot.on.message(text=['начать', 'start', '/start'])
    async def start_handler(message: Message) -> None:
        await message.answer(
            'Привет! Это бот клуба «Аврора».',
            keyboard=await _main_menu(message.from_id),
        )

    @bot.on.message(payload={'cmd': 'status'})
    @bot.on.message(text=['мой статус', 'статус'])
    async def status_handler(message: Message) -> None:
        await _show_status(ctx, message)

    @bot.on.message(payload={'cmd': 'calendar'})
    @bot.on.message(text=['календарь'])
    async def calendar_current(message: Message) -> None:
        today = datetime.now(UTC).date()
        period = MonthPeriod.from_date(today)
        await _show_calendar(ctx, message, period, schedule_url, from_date=today)

    @bot.on.message(text=['календарь <raw>'])
    async def calendar_month(message: Message, raw: str) -> None:
        try:
            period = MonthPeriod.parse(raw)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _show_calendar(ctx, message, period, schedule_url)


_STATUS_LABELS = {
    'pending': '⏳ ожидает подтверждения',
    'active': '✅ активен',
    'rejected': '⛔ отклонён',
}


async def _show_status(ctx: BotContext, message: Message) -> None:
    """Показывает профиль пользователя (статус, роли)."""
    user = await ctx.registration.get_profile(message.from_id)
    if user is None:
        await message.answer(
            'Вы ещё не зарегистрированы. Нажмите «Регистрация», '
            'чтобы подать заявку.'
        )
        return
    status = _STATUS_LABELS.get(user.status.value, user.status.value)
    roles = ', '.join(sorted(r.value for r in user.roles)) or '—'
    await message.answer(
        f'👤 {user.full_name}\nСтатус: {status}\nРоли: {roles}'
    )


async def _show_calendar(
    ctx: BotContext,
    message: Message,
    period: MonthPeriod,
    schedule_url: str,
    *,
    from_date: date | None = None,
) -> None:
    """Отправляет список событий календаря за месяц (доступно всем).

    ``from_date`` — только для команды «Календарь» без периода: прошедшие
    тренировки/игры текущего месяца из списка убираются (см.
    ``CalendarUseCases.list_month``). При явном запросе месяца не
    передаётся — там нужен весь месяц целиком, для истории.
    """
    events = await ctx.calendar.list_month(period, from_date=from_date)
    keyboard = keyboards.schedule_link(schedule_url)
    if not events:
        await message.answer(
            f'На {period.label()} событий нет.', keyboard=keyboard
        )
        return
    lines = [f'📅 Календарь на {period.label()}:', '']
    for ev in events:
        label = _EVENT_LABELS.get(ev.event_type, ev.event_type.value)
        when = ev.event_date.strftime('%d.%m')
        if ev.event_time is not None:
            when += ev.event_time.strftime(' %H:%M')
        place = f' — {ev.place}' if ev.place else ''
        lines.append(f'{when} {label}{place}')
    await message.answer('\n'.join(lines), keyboard=keyboard)
