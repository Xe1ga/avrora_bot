"""Хендлеры разовых посещений и тарифа (ТЗ 3.2 п.4)."""

from datetime import UTC, date, datetime

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.adapters.vk.states import OneTimePaymentEditState, OneTimeState
from avrora_bot.application.services.permissions import has_access
from avrora_bot.application.services.user_lookup import vk_id_label
from avrora_bot.application.use_cases.one_time import VisitRow
from avrora_bot.domain.enums import PaymentStatus, RoleName, TariffKind
from avrora_bot.domain.errors import DomainError

_ONE_TIME_HELP_TEXT = (
    '🎫 Разовые посещения:\n\n'
    '• «разовый тариф <сумма>» — изменить тариф разового посещения\n'
    '• «посетили [дата]» — зафиксировать посещение; бот отдельным '
    'сообщением запросит список vk_id/ФИО посетивших\n'
    '  Дата ДД.ММ.ГГГГ, по умолчанию — сегодня\n'
    '• «разовые <период>» — список посещений за месяц.\n'
    '  Пример: разовые 2026-09\n'
    '• «разовое оплатил <vk_id или ФИО>» — отметить оплаченным самое '
    'старое неоплаченное посещение участника\n'
    '• «редактировать оплату <id>» — изменить дату/сумму/статус/'
    'получателя оплаты (кнопками)\n'
    '• «удалить оплату <id>» — удалить запись о посещении\n\n'
    'Вместо vk_id можно указать фамилию, «Фамилия Имя» или полное ФИО — '
    'если совпадений несколько, бот покажет список для уточнения.'
)

# Поле → (подсказка с текущим значением, состояние для ввода нового) —
# по аналогии с ``user_edit._FIELD_PROMPTS``. «paid»/«unpaid» не входят
# сюда: это не текстовый ввод, а прямое действие по нажатию кнопки.
_VISIT_FIELD_PROMPTS: dict[str, tuple[str, str]] = {
    'date': (
        'Текущая дата: {value}\nВведите новую дату (ДД.ММ.ГГГГ):',
        OneTimePaymentEditState.DATE,
    ),
    'amount': (
        'Текущая сумма: {value} ₽\nВведите новую сумму:',
        OneTimePaymentEditState.AMOUNT,
    ),
    'marked_by': (
        'Сейчас принял: {value}\n'
        'Введите vk_id или ФИО того, кто принял оплату:',
        OneTimePaymentEditState.MARKED_BY,
    ),
}


def register(bot: Bot, ctx: BotContext) -> None:
    """Регистрирует хендлеры разовых посещений."""
    dispenser = bot.state_dispenser

    async def _current_state(peer_id: int) -> str | None:
        peer = await dispenser.get(peer_id)
        if peer is None:
            return None
        state = peer.state
        return (
            state if isinstance(state, str) else getattr(state, 'state', None)
        )

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

    async def _show_visit_fields(message: Message, row: VisitRow) -> None:
        await dispenser.set(
            message.peer_id,
            OneTimePaymentEditState.SELECT_FIELD,
            visit_id=row.visit.id,
            date=row.visit.visit_date,
            amount=row.visit.amount,
            marked_by=row.marked_by_name,
        )
        await message.answer(
            _format_visit(row), keyboard=keyboards.edit_visit_fields()
        )

    async def _apply_visit(message: Message, setter, value: object) -> None:
        peer = await dispenser.get(message.peer_id)
        visit_id = peer.payload['visit_id']
        try:
            row = await setter(message.from_id, visit_id, value)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _show_visit_fields(message, row)

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
            f'• {outcome.user.full_name} '
            f'({vk_id_label(outcome.user.vk_id)}), '
            f'{outcome.visit.amount} ₽ [id {outcome.visit.id}]'
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
            line = (
                f'{mark} {row.visit.visit_date.strftime("%d.%m")} — '
                f'{row.full_name} '
                f'({row.visit.amount} ₽) [id {row.visit.id}]'
            )
            if row.marked_by_name is not None:
                line += f' — принял: {row.marked_by_name}'
            lines.append(line)
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
            f'({vk_id_label(outcome.user.vk_id)}): оплачено ✅.'
        )

    @bot.on.message(text=['редактировать оплату <visit_id:int>'])
    async def start_edit_visit(message: Message, visit_id: int) -> None:
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not has_access(roles, RoleName.COLLECTOR):
            await message.answer(
                '⚠️ Команда доступна только сборщику платежей.'
            )
            return
        try:
            row = await ctx.one_time.get_visit(message.from_id, visit_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _show_visit_fields(message, row)

    @bot.on.message(
        payload_contains={'cmd': 'edit_visit_field'},
        state=OneTimePaymentEditState.SELECT_FIELD,
    )
    async def select_visit_field(message: Message) -> None:
        field = _payload_field(message)
        peer = await dispenser.get(message.peer_id)
        visit_id = peer.payload['visit_id']
        if field in ('paid', 'unpaid'):
            try:
                row = await ctx.one_time.set_visit_status(
                    message.from_id, visit_id, field == 'paid'
                )
            except DomainError as exc:
                await message.answer(f'⚠️ {exc}')
                return
            await _show_visit_fields(message, row)
            return
        prompt = _VISIT_FIELD_PROMPTS.get(field)
        if prompt is None:
            return
        template, state = prompt
        current = peer.payload.get(field)
        await dispenser.set(message.peer_id, state, **peer.payload)
        await message.answer(
            template.format(value=_visit_display(current)),
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=OneTimePaymentEditState.DATE)
    async def step_visit_date(message: Message) -> None:
        try:
            visit_date = helpers.parse_birthdate(message.text)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}\nПовторите ввод даты:')
            return
        await _apply_visit(message, ctx.one_time.set_visit_date, visit_date)

    @bot.on.message(state=OneTimePaymentEditState.AMOUNT)
    async def step_visit_amount(message: Message) -> None:
        try:
            amount = helpers.parse_amount(message.text)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}\nПовторите ввод суммы:')
            return
        await _apply_visit(message, ctx.one_time.set_visit_amount, amount)

    @bot.on.message(state=OneTimePaymentEditState.MARKED_BY)
    async def step_visit_marked_by(message: Message) -> None:
        await _apply_visit(
            message, ctx.one_time.set_visit_marked_by, message.text.strip()
        )

    @bot.on.message(payload={'cmd': 'edit_visit_done'})
    async def finish_edit_visit(message: Message) -> None:
        # См. комментарий в user_edit.finish_edit о StatePeer.state.__eq__.
        if (
            not await _current_state(message.peer_id)  # noqa: SIM201
            == OneTimePaymentEditState.SELECT_FIELD
        ):
            return
        await dispenser.delete(message.peer_id)
        await message.answer('Изменения сохранены.')

    @bot.on.message(text=['удалить оплату <visit_id:int>'])
    async def delete_visit(message: Message, visit_id: int) -> None:
        try:
            await ctx.one_time.delete_visit(message.from_id, visit_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(f'Запись об оплате id {visit_id} удалена.')

    @bot.on.message(payload={'cmd': 'one_time_help'})
    async def one_time_help(message: Message) -> None:
        roles = await ctx.user_management.effective_roles(message.from_id)
        if not has_access(roles, RoleName.COLLECTOR):
            await message.answer('⚠️ Команда доступна только сборщику платежей.')
            return
        await message.answer(_ONE_TIME_HELP_TEXT)


def _payload_field(message: Message) -> str:
    """Извлекает выбранное поле из payload инлайн-кнопки."""
    payload = message.get_payload_json() or {}
    return str(payload.get('field', ''))


def _visit_display(value: object) -> str:
    """Форматирует текущее значение поля разового посещения для показа."""
    if value is None:
        return '—'
    if isinstance(value, date):
        return value.strftime('%d.%m.%Y')
    return str(value)


def _format_visit(row: VisitRow) -> str:
    """Текущие данные записи + приглашение выбрать поле для правки."""
    mark = (
        'оплачено ✅' if row.visit.status is PaymentStatus.PAID else 'не оплачено ❌'
    )
    lines = [
        f'🎫 Разовое посещение id {row.visit.id}',
        f'Участник: {row.full_name}',
        f'Дата: {row.visit.visit_date.strftime("%d.%m.%Y")}',
        f'Сумма: {row.visit.amount} ₽',
        f'Статус: {mark}',
    ]
    lines.append(f'Принял: {row.marked_by_name or "—"}')
    lines.append('')
    lines.append('Выберите, что изменить:')
    return '\n'.join(lines)


def _parse_date(raw: str) -> date:
    """Разбирает дату ДД.ММ.ГГГГ (переиспользует парсер ДР)."""
    return helpers.parse_birthdate(raw)
