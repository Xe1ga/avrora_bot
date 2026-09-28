"""Хендлеры финансового учёта: расходы, передачи денег, корректировки.

Раздел «💸 Расходы» (сборщик/админ) — кнопки с пошаговыми диалогами и те
же операции текстовыми командами, по образцу handlers/one_time.py. Права
проверяет ``FinanceUseCases``: сборщик — только свой счёт, админ — любой.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from decimal import Decimal

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.adapters.vk.states import (
    AdjustmentState,
    ExpenseEditState,
    ExpenseState,
    TransferState,
)
from avrora_bot.application.services.permissions import has_access
from avrora_bot.application.use_cases.finance import (
    EXPENSE_CATEGORY_LABELS,
    AdjustmentRow,
    ExpenseRow,
    TransferRow,
    guess_category,
)
from avrora_bot.domain.enums import ExpenseCategory, RoleName
from avrora_bot.domain.errors import DomainError, ValidationError
from avrora_bot.domain.value_objects import MonthPeriod

_EXPENSES_HELP_TEXT = (
    '💸 Расходы и деньги на руках:\n\n'
    '• «расход <сумма> <описание>» (кнопка «➕ Расход») — записать расход '
    'со своего счёта сегодняшним днём; тип (зал/тренер/прочее) бот '
    'определит по описанию.\n'
    '  Пример: расход 1500 Оплата тренер Елена\n'
    '• «расходы <период>» (кнопка «💬 Расходы за месяц» — текущий месяц) — '
    'список расходов в чат.\n'
    '  Пример: расходы 2026-09\n'
    '• «редактировать расход <id>» — изменить дату/сумму/тип/описание/'
    'примечание (кнопками)\n'
    '• «удалить расход <id>»\n\n'
    '• «передать <сумма> <кому>» (кнопка «🔁 Передать») — передать деньги '
    'клуба другому человеку, например на оплату зала.\n'
    '  Пример: передать 1500 Седова\n'
    '• «передачи <период>» — список передач за месяц\n'
    '• «удалить передачу <id>»\n\n'
    '• «остаток [ДД.ММ.ГГГГ]» (кнопка «🏦 Остатки») — у кого сколько денег '
    'клуба на руках на дату (по умолчанию — сегодня)\n'
    '• «мой счёт» — свой остаток с разбивкой за месяц\n\n'
    'Сборщик записывает операции только со своего счёта и правит только '
    'свои записи.'
)

_ADMIN_HELP_TEXT = (
    '\n\nАдминистратору:\n'
    '• «передача <сумма> от <кого> кому <кому>» — передача между любыми '
    'людьми\n'
    '• при записи расхода кнопкой бот спросит, с чьего счёта; в правке '
    'расхода есть кнопка «Счёт»\n'
    '• «корректировка» — начальный остаток или исправление остатка '
    '(сумма со знаком: 1500 или -200)\n'
    '• «корректировки» — список корректировок\n'
    '• «удалить корректировку <id>»'
)

_ONLY_COLLECTOR = '⚠️ Команда доступна только сборщику платежей.'
_ONLY_ADMIN = '⚠️ Команда доступна только администратору.'

# Поле правки расхода → (подсказка с текущим значением, состояние ввода).
_EXPENSE_FIELD_PROMPTS: dict[str, tuple[str, str]] = {
    'date': (
        'Текущая дата: {value}\nВведите новую дату (ДД.ММ.ГГГГ):',
        ExpenseEditState.DATE,
    ),
    'amount': (
        'Текущая сумма: {value} ₽\nВведите новую сумму:',
        ExpenseEditState.AMOUNT,
    ),
    'description': (
        'Текущее описание: {value}\nВведите новое описание:',
        ExpenseEditState.DESCRIPTION,
    ),
    'note': (
        'Текущее примечание: {value}\n'
        'Введите новое примечание («-» — очистить):',
        ExpenseEditState.NOTE,
    ),
    'account': (
        'Сейчас со счёта: {value}\nВведите vk_id или ФИО владельца счёта:',
        ExpenseEditState.ACCOUNT,
    ),
}


def register(bot: Bot, ctx: BotContext) -> None:  # noqa: C901, PLR0915
    """Регистрирует хендлеры расходов, передач и корректировок."""
    dispenser = bot.state_dispenser

    async def _roles(vk_id: int) -> frozenset[RoleName]:
        return await ctx.user_management.effective_roles(vk_id)

    async def _is_collector(vk_id: int) -> bool:
        return has_access(await _roles(vk_id), RoleName.COLLECTOR)

    async def _is_admin(vk_id: int) -> bool:
        return has_access(await _roles(vk_id), RoleName.ADMIN)

    async def _current_state(peer_id: int) -> str | None:
        peer = await dispenser.get(peer_id)
        if peer is None:
            return None
        state = peer.state
        return (
            state if isinstance(state, str) else getattr(state, 'state', None)
        )

    async def _payload(peer_id: int) -> dict:
        peer = await dispenser.get(peer_id)
        return dict(peer.payload) if peer else {}

    def _today() -> date:
        return datetime.now(UTC).date()

    # ───────────────────────────── раздел ──────────────────────────────

    @bot.on.message(payload={'cmd': 'expenses_help'})
    async def expenses_help(message: Message) -> None:
        if not await _is_collector(message.from_id):
            await message.answer(_ONLY_COLLECTOR)
            return
        text = _EXPENSES_HELP_TEXT
        if await _is_admin(message.from_id):
            text += _ADMIN_HELP_TEXT
        await message.answer(text, keyboard=keyboards.expense_actions())

    # ─────────────────────── запись расхода кнопкой ────────────────────

    @bot.on.message(payload={'cmd': 'expense_add'})
    async def start_add_expense(message: Message) -> None:
        if not await _is_collector(message.from_id):
            await message.answer(_ONLY_COLLECTOR)
            return
        await dispenser.set(message.peer_id, ExpenseState.CATEGORY)
        await message.answer(
            'Выберите тип расхода:',
            keyboard=keyboards.expense_category('expense_category'),
        )

    @bot.on.message(
        payload_contains={'cmd': 'expense_category'},
        state=ExpenseState.CATEGORY,
    )
    async def step_expense_category(message: Message) -> None:
        category = _payload_category(message)
        if category is None:
            return
        await dispenser.set(
            message.peer_id, ExpenseState.AMOUNT, category=category
        )
        await message.answer(
            f'Тип: {EXPENSE_CATEGORY_LABELS[category]}.\nВведите сумму:',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=ExpenseState.AMOUNT)
    async def step_expense_amount(message: Message) -> None:
        try:
            amount = _parse_positive_amount(message.text)
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПовторите ввод суммы:', keyboard=keyboards.cancel()
            )
            return
        payload = await _payload(message.peer_id)
        await dispenser.set(
            message.peer_id, ExpenseState.DESCRIPTION, **payload, amount=amount
        )
        await message.answer(
            'Введите описание — как в таблице, например «Оплата тренер '
            'Елена» или «Оплата зала сентябрь»:',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=ExpenseState.DESCRIPTION)
    async def step_expense_description(message: Message) -> None:
        description = message.text.strip()
        if not description:
            await message.answer(
                '⚠️ Описание не может быть пустым. Введите описание:',
                keyboard=keyboards.cancel(),
            )
            return
        payload = await _payload(message.peer_id)
        await dispenser.set(
            message.peer_id,
            ExpenseState.DATE,
            **payload,
            description=description,
        )
        await message.answer(
            'Введите дату расхода (ДД.ММ.ГГГГ) или нажмите «Сегодня»:',
            keyboard=keyboards.date_prompt(),
        )

    @bot.on.message(state=ExpenseState.DATE)
    async def step_expense_date(message: Message) -> None:
        try:
            spent_on = helpers.parse_visit_date(message.text, _today())
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПовторите ввод даты или нажмите «Сегодня».',
                keyboard=keyboards.date_prompt(),
            )
            return
        payload = await _payload(message.peer_id)
        payload['spent_on'] = spent_on
        if await _is_admin(message.from_id):
            await dispenser.set(
                message.peer_id, ExpenseState.ACCOUNT, **payload
            )
            await message.answer(
                'С чьего счёта оплачено? Введите vk_id или ФИО, либо нажмите '
                '«Мой счёт»:',
                keyboard=keyboards.own_account_prompt(),
            )
            return
        await _save_expense(message, payload, account=None, can_retry=False)

    @bot.on.message(state=ExpenseState.ACCOUNT)
    async def step_expense_account(message: Message) -> None:
        raw = message.text.strip()
        account = None if raw.lower() == 'мой счёт' else raw
        await _save_expense(
            message,
            await _payload(message.peer_id),
            account=account,
            can_retry=True,
        )

    async def _save_expense(
        message: Message,
        payload: dict,
        *,
        account: str | None,
        can_retry: bool,
    ) -> None:
        """Сохраняет расход из диалога.

        :param can_retry: ошибку можно исправить повторным вводом счёта
            (шаг «с чьего счёта» у администратора) — тогда диалог не
            закрывается.
        """
        try:
            row = await ctx.finance.add_expense(
                message.from_id,
                spent_on=payload['spent_on'],
                category=payload['category'],
                description=payload['description'],
                amount=payload['amount'],
                account=account,
            )
        except DomainError as exc:
            if can_retry:
                await message.answer(
                    f'⚠️ {exc}\nВведите vk_id/ФИО или нажмите «Мой счёт».',
                    keyboard=keyboards.own_account_prompt(),
                )
                return
            await dispenser.delete(message.peer_id)
            await message.answer(f'⚠️ {exc}')
            return
        await dispenser.delete(message.peer_id)
        await message.answer(
            f'Расход записан ✅\n{_expense_line(row)}\n\n'
            f'Изменить: «редактировать расход {row.expense.id}».'
        )

    # ─────────────────────── быстрые команды расходов ──────────────────

    @bot.on.message(text=['расход <amount> <description>'])
    async def quick_add_expense(
        message: Message, amount: str, description: str
    ) -> None:
        try:
            value = _parse_positive_amount(amount)
            row = await ctx.finance.add_expense(
                message.from_id,
                spent_on=_today(),
                category=guess_category(description),
                description=description,
                amount=value,
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(
            f'Расход записан ✅\n{_expense_line(row)}\n\n'
            f'Изменить дату, тип или счёт: «редактировать расход '
            f'{row.expense.id}».'
        )

    async def _send_month_expenses(
        message: Message, month: MonthPeriod
    ) -> None:
        try:
            rows = await ctx.finance.month_expenses(message.from_id, month)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        if not rows:
            await message.answer(f'Расходов в {month.label()} нет.')
            return
        total = sum((r.expense.amount for r in rows), Decimal(0))
        lines = [f'Расходы за {month.label()}:', '']
        lines.extend(_expense_line(row) for row in rows)
        lines.extend(['', f'Итого: {total} ₽'])
        for account, amount in _totals_by_account(rows).items():
            lines.append(f'  со счёта {account}: {amount} ₽')
        for part in helpers.split_message('\n'.join(lines)):
            await message.answer(part)

    @bot.on.message(text=['расходы <period>'])
    async def list_expenses(message: Message, period: str) -> None:
        try:
            month = helpers.parse_period(period)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _send_month_expenses(message, month)

    @bot.on.message(payload={'cmd': 'expenses_chat'})
    async def expenses_chat_button(message: Message) -> None:
        await _send_month_expenses(message, MonthPeriod.from_date(_today()))

    @bot.on.message(text=['удалить расход <expense_id:int>'])
    async def delete_expense(message: Message, expense_id: int) -> None:
        try:
            await ctx.finance.delete_expense(message.from_id, expense_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(f'Расход id {expense_id} удалён.')

    # ─────────────────────────── правка расхода ────────────────────────

    async def _show_expense_fields(message: Message, row: ExpenseRow) -> None:
        await dispenser.set(
            message.peer_id,
            ExpenseEditState.SELECT_FIELD,
            expense_id=row.expense.id,
            date=row.expense.spent_on,
            amount=row.expense.amount,
            description=row.expense.description,
            note=row.expense.note,
            account=row.account_name,
        )
        await message.answer(
            _format_expense(row),
            keyboard=keyboards.edit_expense_fields(
                is_admin=await _is_admin(message.from_id)
            ),
        )

    async def _apply_expense(
        message: Message,
        setter: Callable[[int, int, object], Awaitable[ExpenseRow]],
        value: object,
    ) -> None:
        payload = await _payload(message.peer_id)
        try:
            row = await setter(message.from_id, payload['expense_id'], value)
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПовторите ввод или нажмите «Отмена».',
                keyboard=keyboards.cancel(),
            )
            return
        await _show_expense_fields(message, row)

    @bot.on.message(text=['редактировать расход <expense_id:int>'])
    async def start_edit_expense(message: Message, expense_id: int) -> None:
        try:
            row = await ctx.finance.get_expense(message.from_id, expense_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _show_expense_fields(message, row)

    @bot.on.message(
        payload_contains={'cmd': 'edit_expense_field'},
        state=ExpenseEditState.SELECT_FIELD,
    )
    async def select_expense_field(message: Message) -> None:
        field = _payload_value(message, 'field')
        payload = await _payload(message.peer_id)
        if field == 'category':
            category = _payload_category(message)
            if category is None:
                # Первое нажатие «Тип» — показать варианты; второе (с
                # value) — применить выбранный.
                await message.answer(
                    'Выберите тип расхода:',
                    keyboard=keyboards.expense_category('edit_expense_field'),
                )
                return
            await _apply_expense(
                message, ctx.finance.set_expense_category, category
            )
            return
        prompt = _EXPENSE_FIELD_PROMPTS.get(field)
        if prompt is None:
            return
        template, state = prompt
        await dispenser.set(message.peer_id, state, **payload)
        await message.answer(
            template.format(value=_display(payload.get(field))),
            keyboard=keyboards.cancel(),
        )

    async def _back_to_fields_on_error(
        message: Message, exc: DomainError
    ) -> None:
        await message.answer(
            f'⚠️ {exc}\nПовторите ввод или нажмите «Отмена».',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=ExpenseEditState.DATE)
    async def step_edit_expense_date(message: Message) -> None:
        try:
            spent_on = helpers.parse_birthdate(message.text)
        except DomainError as exc:
            await _back_to_fields_on_error(message, exc)
            return
        await _apply_expense(message, ctx.finance.set_expense_date, spent_on)

    @bot.on.message(state=ExpenseEditState.AMOUNT)
    async def step_edit_expense_amount(message: Message) -> None:
        try:
            amount = helpers.parse_amount(message.text)
        except DomainError as exc:
            await _back_to_fields_on_error(message, exc)
            return
        await _apply_expense(message, ctx.finance.set_expense_amount, amount)

    @bot.on.message(state=ExpenseEditState.DESCRIPTION)
    async def step_edit_expense_description(message: Message) -> None:
        await _apply_expense(
            message, ctx.finance.set_expense_description, message.text
        )

    @bot.on.message(state=ExpenseEditState.NOTE)
    async def step_edit_expense_note(message: Message) -> None:
        await _apply_expense(
            message,
            ctx.finance.set_expense_note,
            helpers.parse_optional(message.text),
        )

    @bot.on.message(state=ExpenseEditState.ACCOUNT)
    async def step_edit_expense_account(message: Message) -> None:
        await _apply_expense(
            message, ctx.finance.set_expense_account, message.text.strip()
        )

    @bot.on.message(payload={'cmd': 'edit_expense_done'})
    async def finish_edit_expense(message: Message) -> None:
        # См. комментарий в user_edit.finish_edit о StatePeer.state.__eq__.
        if (
            not await _current_state(message.peer_id)  # noqa: SIM201
            == ExpenseEditState.SELECT_FIELD
        ):
            return
        await dispenser.delete(message.peer_id)
        await message.answer('Изменения сохранены.')

    # ───────────────────────────── передачи ────────────────────────────

    async def _reply_transfer(message: Message, row: TransferRow) -> None:
        await message.answer(
            f'Передача записана ✅\n{_transfer_line(row)}\n\n'
            f'Отменить: «удалить передачу {row.transfer.id}».'
        )

    @bot.on.message(payload={'cmd': 'transfer_add'})
    async def start_add_transfer(message: Message) -> None:
        if not await _is_collector(message.from_id):
            await message.answer(_ONLY_COLLECTOR)
            return
        await dispenser.set(message.peer_id, TransferState.TARGET)
        await message.answer(
            'Кому вы передали деньги? Введите vk_id или ФИО:',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=TransferState.TARGET)
    async def step_transfer_target(message: Message) -> None:
        target = message.text.strip()
        if not target:
            await message.answer(
                '⚠️ Введите vk_id или ФИО получателя:',
                keyboard=keyboards.cancel(),
            )
            return
        await dispenser.set(message.peer_id, TransferState.AMOUNT, to=target)
        await message.answer('Введите сумму:', keyboard=keyboards.cancel())

    @bot.on.message(state=TransferState.AMOUNT)
    async def step_transfer_amount(message: Message) -> None:
        try:
            amount = _parse_positive_amount(message.text)
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПовторите ввод суммы:', keyboard=keyboards.cancel()
            )
            return
        payload = await _payload(message.peer_id)
        await dispenser.set(
            message.peer_id, TransferState.NOTE, **payload, amount=amount
        )
        await message.answer(
            'Примечание — зачем передали (например, «на оплату зала»), '
            'или «-» без примечания:',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=TransferState.NOTE)
    async def step_transfer_note(message: Message) -> None:
        payload = await _payload(message.peer_id)
        await dispenser.delete(message.peer_id)
        try:
            row = await ctx.finance.add_transfer(
                message.from_id,
                transferred_on=_today(),
                to=payload['to'],
                amount=payload['amount'],
                note=helpers.parse_optional(message.text),
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _reply_transfer(message, row)

    # Регистрируется раньше «передать <сумма> <кому>»: шаблоны не
    # пересекаются по первому слову, но так порядок очевиден.
    @bot.on.message(text=['передача <amount> от <source> кому <target>'])
    async def admin_transfer(
        message: Message, amount: str, source: str, target: str
    ) -> None:
        try:
            row = await ctx.finance.add_transfer(
                message.from_id,
                transferred_on=_today(),
                to=target,
                amount=_parse_positive_amount(amount),
                source=source,
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _reply_transfer(message, row)

    @bot.on.message(text=['передать <amount> <target>'])
    async def quick_transfer(
        message: Message, amount: str, target: str
    ) -> None:
        try:
            row = await ctx.finance.add_transfer(
                message.from_id,
                transferred_on=_today(),
                to=target,
                amount=_parse_positive_amount(amount),
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await _reply_transfer(message, row)

    @bot.on.message(text=['передачи <period>'])
    async def list_transfers(message: Message, period: str) -> None:
        try:
            month = helpers.parse_period(period)
            rows = await ctx.finance.month_transfers(message.from_id, month)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        if not rows:
            await message.answer(f'Передач в {month.label()} нет.')
            return
        lines = [f'Передачи за {month.label()}:', '']
        lines.extend(_transfer_line(row) for row in rows)
        for part in helpers.split_message('\n'.join(lines)):
            await message.answer(part)

    @bot.on.message(text=['удалить передачу <transfer_id:int>'])
    async def delete_transfer(message: Message, transfer_id: int) -> None:
        try:
            await ctx.finance.delete_transfer(message.from_id, transfer_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(f'Передача id {transfer_id} удалена.')

    # ─────────────────────────── корректировки ─────────────────────────

    @bot.on.message(text=['корректировка'])
    async def start_adjustment(message: Message) -> None:
        if not await _is_admin(message.from_id):
            await message.answer(_ONLY_ADMIN)
            return
        await dispenser.set(message.peer_id, AdjustmentState.TARGET)
        await message.answer(
            'Чей остаток корректируем? Введите vk_id или ФИО:',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=AdjustmentState.TARGET)
    async def step_adjustment_target(message: Message) -> None:
        target = message.text.strip()
        if not target:
            await message.answer(
                '⚠️ Введите vk_id или ФИО:', keyboard=keyboards.cancel()
            )
            return
        await dispenser.set(
            message.peer_id, AdjustmentState.AMOUNT, target=target
        )
        await message.answer(
            'Введите сумму со знаком: «1500» — добавить на счёт, «-200» — '
            'списать.',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=AdjustmentState.AMOUNT)
    async def step_adjustment_amount(message: Message) -> None:
        try:
            amount = helpers.parse_amount(message.text)
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПовторите ввод суммы:', keyboard=keyboards.cancel()
            )
            return
        payload = await _payload(message.peer_id)
        await dispenser.set(
            message.peer_id, AdjustmentState.DATE, **payload, amount=amount
        )
        await message.answer(
            'На какую дату (ДД.ММ.ГГГГ)? Для начального остатка — дата, на '
            'которую он посчитан.',
            keyboard=keyboards.date_prompt(),
        )

    @bot.on.message(state=AdjustmentState.DATE)
    async def step_adjustment_date(message: Message) -> None:
        try:
            adjusted_on = helpers.parse_visit_date(message.text, _today())
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}\nПовторите ввод даты или нажмите «Сегодня».',
                keyboard=keyboards.date_prompt(),
            )
            return
        payload = await _payload(message.peer_id)
        await dispenser.set(
            message.peer_id,
            AdjustmentState.REASON,
            **payload,
            adjusted_on=adjusted_on,
        )
        await message.answer(
            'Причина (например, «Остаток по таблице на 19.08.2026»):',
            keyboard=keyboards.cancel(),
        )

    @bot.on.message(state=AdjustmentState.REASON)
    async def step_adjustment_reason(message: Message) -> None:
        payload = await _payload(message.peer_id)
        try:
            row = await ctx.finance.add_adjustment(
                message.from_id,
                adjusted_on=payload['adjusted_on'],
                target=payload['target'],
                amount=payload['amount'],
                reason=message.text,
            )
        except DomainError as exc:
            await dispenser.delete(message.peer_id)
            await message.answer(f'⚠️ {exc}')
            return
        await dispenser.delete(message.peer_id)
        await message.answer(
            f'Корректировка записана ✅\n{_adjustment_line(row)}\n\n'
            f'Отменить: «удалить корректировку {row.adjustment.id}».'
        )

    @bot.on.message(text=['корректировки'])
    async def list_adjustments(message: Message) -> None:
        try:
            rows = await ctx.finance.adjustments_until(
                message.from_id, _today()
            )
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        if not rows:
            await message.answer('Корректировок нет.')
            return
        lines = ['Корректировки остатков:', '']
        lines.extend(_adjustment_line(row) for row in rows)
        for part in helpers.split_message('\n'.join(lines)):
            await message.answer(part)

    @bot.on.message(text=['удалить корректировку <adjustment_id:int>'])
    async def delete_adjustment(message: Message, adjustment_id: int) -> None:
        try:
            await ctx.finance.delete_adjustment(message.from_id, adjustment_id)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}')
            return
        await message.answer(f'Корректировка id {adjustment_id} удалена.')


def _parse_positive_amount(raw: str) -> Decimal:
    """Сумма операции; знак и ноль отсекаются ещё до use case'а."""
    amount = helpers.parse_amount(raw)
    if not amount.is_finite() or amount <= 0:
        raise ValidationError('Сумма должна быть больше нуля')
    return amount


def _payload_value(message: Message, key: str) -> str:
    payload = message.get_payload_json() or {}
    return str(payload.get(key, ''))


def _payload_category(message: Message) -> ExpenseCategory | None:
    try:
        return ExpenseCategory(_payload_value(message, 'value'))
    except ValueError:
        return None


def _display(value: object) -> str:
    if value is None:
        return '—'
    if isinstance(value, date):
        return value.strftime('%d.%m.%Y')
    return str(value)


def _totals_by_account(rows: list[ExpenseRow]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        totals[row.account_name] = (
            totals.get(row.account_name, Decimal(0)) + row.expense.amount
        )
    return totals


def _expense_line(row: ExpenseRow) -> str:
    expense = row.expense
    line = (
        f'{expense.spent_on.strftime("%d.%m")} — {expense.description} '
        f'({EXPENSE_CATEGORY_LABELS[expense.category].lower()}), '
        f'{expense.amount} ₽, со счёта {row.account_name} [id {expense.id}]'
    )
    if expense.note:
        line += f' ({expense.note})'
    return line


def _format_expense(row: ExpenseRow) -> str:
    expense = row.expense
    return '\n'.join(
        [
            f'💸 Расход id {expense.id}',
            f'Дата: {expense.spent_on.strftime("%d.%m.%Y")}',
            f'Тип: {EXPENSE_CATEGORY_LABELS[expense.category]}',
            f'Описание: {expense.description}',
            f'Сумма: {expense.amount} ₽',
            f'Со счёта: {row.account_name}',
            f'Примечание: {expense.note or "—"}',
            '',
            'Выберите, что изменить:',
        ]
    )


def _transfer_line(row: TransferRow) -> str:
    transfer = row.transfer
    line = (
        f'{transfer.transferred_on.strftime("%d.%m")} — {row.from_name} → '
        f'{row.to_name}: {transfer.amount} ₽ [id {transfer.id}]'
    )
    if transfer.note:
        line += f' ({transfer.note})'
    return line


def _adjustment_line(row: AdjustmentRow) -> str:
    adjustment = row.adjustment
    sign = '+' if adjustment.amount > 0 else ''
    return (
        f'{adjustment.adjusted_on.strftime("%d.%m.%Y")} — {row.user_name}: '
        f'{sign}{adjustment.amount} ₽, {adjustment.reason} '
        f'[id {adjustment.id}]'
    )
