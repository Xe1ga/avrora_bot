"""Use case'ы финансового учёта: расходы, передачи денег, корректировки.

«Счёт» — человек, у которого на руках деньги клуба (см.
``domain.services.balance_calc``). Права:

* расход и передачу сборщик записывает только со **своего** счёта и
  правит/удаляет только их; администратор — с любого счёта и любые записи;
* корректировки остатка (начальный остаток, исправление расхождений) —
  только администратор.

В ``action_log`` пишутся id, суммы и типы — без описаний и примечаний:
там бывают имена тренеров и участников, а журнал не шифруется.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.application.services.user_lookup import resolve_user
from avrora_bot.domain.entities import (
    AccountTransfer,
    BalanceAdjustment,
    Expense,
    User,
)
from avrora_bot.domain.enums import ExpenseCategory, RoleName
from avrora_bot.domain.errors import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway
from avrora_bot.domain.value_objects import MonthPeriod

UowFactory = Callable[[], UnitOfWork]

MAX_DESCRIPTION_LEN = 256
MAX_NOTE_LEN = 512
MAX_REASON_LEN = 256

_KOPECK = Decimal('0.01')
# Numeric(12, 2): до 10 знаков в целой части.
_MAX_AMOUNT = Decimal(10) ** 10

EXPENSE_CATEGORY_LABELS: dict[ExpenseCategory, str] = {
    ExpenseCategory.HALL: 'Зал',
    ExpenseCategory.COACH: 'Тренер',
    ExpenseCategory.OTHER: 'Прочее',
}


def guess_category(description: str) -> ExpenseCategory:
    """Тип расхода по описанию для быстрой команды «расход <сумма> <…>».

    «Оплата зала сентябрь» → зал, «Оплата тренер Елена» → тренер, прочее —
    «прочее»; ошибку всегда можно поправить через «редактировать расход».
    """
    text = description.lower()
    if 'зал' in text:
        return ExpenseCategory.HALL
    if 'тренер' in text:
        return ExpenseCategory.COACH
    return ExpenseCategory.OTHER


@dataclass(frozen=True, slots=True)
class ExpenseRow:
    """Расход с ФИО владельца счёта — для списков и карточки."""

    expense: Expense
    account_name: str


@dataclass(frozen=True, slots=True)
class TransferRow:
    """Передача денег с ФИО отдавшего и получившего."""

    transfer: AccountTransfer
    from_name: str
    to_name: str


@dataclass(frozen=True, slots=True)
class AdjustmentRow:
    """Корректировка остатка с ФИО владельца счёта."""

    adjustment: BalanceAdjustment
    user_name: str


class FinanceUseCases:
    """Расходы, передачи денег между людьми и корректировки остатков."""

    def __init__(self, uow_factory: UowFactory, vk_gateway: VkGateway) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway

    # ───────────────────────────── расходы ─────────────────────────────

    async def add_expense(  # noqa: PLR0913
        self,
        actor_vk_id: int,
        *,
        spent_on: date,
        category: ExpenseCategory,
        description: str,
        amount: Decimal,
        account: str | None = None,
        note: str | None = None,
    ) -> ExpenseRow:
        """Записывает расход.

        :param account: vk_id/ФИО владельца счёта; ``None`` — свой счёт.
            Чужой счёт может указать только администратор.
        """
        description = _validate_text(
            description, 'Описание расхода', MAX_DESCRIPTION_LEN
        )
        _validate_positive(amount)
        _validate_note(note)
        async with self._uow_factory() as uow:
            await self._require_collector(uow, actor_vk_id)
            owner = await self._resolve_account(uow, actor_vk_id, account)
            expense = await uow.expenses.add(
                Expense(
                    spent_on=spent_on,
                    category=category,
                    description=description,
                    amount=amount,
                    account_user_id=owner.id,
                    created_by_vk_id=actor_vk_id,
                    note=note,
                )
            )
            await record_action(
                uow,
                actor_vk_id,
                'expense.add',
                f'expense_id={expense.id} account_user_id={owner.id} '
                f'category={category.value} amount={amount} '
                f'spent_on={spent_on}',
            )
            await uow.commit()
            return ExpenseRow(expense=expense, account_name=owner.full_name)

    async def get_expense(
        self, actor_vk_id: int, expense_id: int
    ) -> ExpenseRow:
        """Расход для просмотра/правки (доступен любому сборщику)."""
        async with self._uow_factory() as uow:
            await self._require_collector(uow, actor_vk_id)
            expense = await _get_expense_or_raise(uow, expense_id)
            return await _expense_row(uow, expense)

    async def month_expenses(
        self, actor_vk_id: int, period: MonthPeriod
    ) -> list[ExpenseRow]:
        """Расходы за месяц в порядке дат (вкладка «РАСХОДЫ»)."""
        async with self._uow_factory() as uow:
            await self._require_collector(uow, actor_vk_id)
            expenses = await uow.expenses.list_for_month(period)
            return [await _expense_row(uow, x) for x in expenses]

    async def set_expense_date(
        self, actor_vk_id: int, expense_id: int, spent_on: date
    ) -> ExpenseRow:
        return await self._update_expense(
            actor_vk_id,
            expense_id,
            f'spent_on={spent_on}',
            lambda x: setattr(x, 'spent_on', spent_on),
        )

    async def set_expense_amount(
        self, actor_vk_id: int, expense_id: int, amount: Decimal
    ) -> ExpenseRow:
        _validate_positive(amount)
        return await self._update_expense(
            actor_vk_id,
            expense_id,
            f'amount={amount}',
            lambda x: setattr(x, 'amount', amount),
        )

    async def set_expense_category(
        self, actor_vk_id: int, expense_id: int, category: ExpenseCategory
    ) -> ExpenseRow:
        return await self._update_expense(
            actor_vk_id,
            expense_id,
            f'category={category.value}',
            lambda x: setattr(x, 'category', category),
        )

    async def set_expense_description(
        self, actor_vk_id: int, expense_id: int, description: str
    ) -> ExpenseRow:
        description = _validate_text(
            description, 'Описание расхода', MAX_DESCRIPTION_LEN
        )
        return await self._update_expense(
            actor_vk_id,
            expense_id,
            'description_set=True',
            lambda x: setattr(x, 'description', description),
        )

    async def set_expense_note(
        self, actor_vk_id: int, expense_id: int, note: str | None
    ) -> ExpenseRow:
        """Меняет примечание (``None`` — очистить)."""
        _validate_note(note)
        return await self._update_expense(
            actor_vk_id,
            expense_id,
            f'note_set={note is not None}',
            lambda x: setattr(x, 'note', note),
        )

    async def set_expense_account(
        self, actor_vk_id: int, expense_id: int, account: str
    ) -> ExpenseRow:
        """Переносит расход на счёт другого человека (только админ)."""
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, actor_vk_id)
            expense = await _get_expense_or_raise(uow, expense_id)
            owner = await resolve_user(uow, account)
            expense.account_user_id = owner.id
            await uow.expenses.update(expense)
            await record_action(
                uow,
                actor_vk_id,
                'expense.edit',
                f'expense_id={expense_id} account_user_id={owner.id}',
            )
            await uow.commit()
            return ExpenseRow(expense=expense, account_name=owner.full_name)

    async def delete_expense(self, actor_vk_id: int, expense_id: int) -> None:
        async with self._uow_factory() as uow:
            await self._require_collector(uow, actor_vk_id)
            expense = await _get_expense_or_raise(uow, expense_id)
            await self._require_owner(
                uow, actor_vk_id, expense.account_user_id, 'расход'
            )
            await uow.expenses.delete(expense_id)
            await record_action(
                uow,
                actor_vk_id,
                'expense.delete',
                f'expense_id={expense_id} amount={expense.amount}',
            )
            await uow.commit()

    async def _update_expense(
        self,
        actor_vk_id: int,
        expense_id: int,
        details: str,
        mutate: Callable[[Expense], None],
    ) -> ExpenseRow:
        async with self._uow_factory() as uow:
            await self._require_collector(uow, actor_vk_id)
            expense = await _get_expense_or_raise(uow, expense_id)
            await self._require_owner(
                uow, actor_vk_id, expense.account_user_id, 'расход'
            )
            mutate(expense)
            await uow.expenses.update(expense)
            await record_action(
                uow,
                actor_vk_id,
                'expense.edit',
                f'expense_id={expense_id} {details}',
            )
            await uow.commit()
            return await _expense_row(uow, expense)

    # ───────────────────────────── передачи ────────────────────────────

    async def add_transfer(  # noqa: PLR0913
        self,
        actor_vk_id: int,
        *,
        transferred_on: date,
        to: str,
        amount: Decimal,
        source: str | None = None,
        note: str | None = None,
    ) -> TransferRow:
        """Записывает передачу денег от ``source`` к ``to``.

        :param source: vk_id/ФИО отдавшего; ``None`` — сам ``actor``.
            Передачу с чужого счёта может записать только администратор.
        """
        _validate_positive(amount)
        _validate_note(note)
        async with self._uow_factory() as uow:
            await self._require_collector(uow, actor_vk_id)
            sender = await self._resolve_account(uow, actor_vk_id, source)
            recipient = await resolve_user(uow, to)
            if recipient.id == sender.id:
                raise ValidationError('Нельзя передать деньги самому себе')
            transfer = await uow.transfers.add(
                AccountTransfer(
                    transferred_on=transferred_on,
                    from_user_id=sender.id,
                    to_user_id=recipient.id,
                    amount=amount,
                    created_by_vk_id=actor_vk_id,
                    note=note,
                )
            )
            await record_action(
                uow,
                actor_vk_id,
                'transfer.add',
                f'transfer_id={transfer.id} from_user_id={sender.id} '
                f'to_user_id={recipient.id} amount={amount} '
                f'transferred_on={transferred_on}',
            )
            await uow.commit()
            return TransferRow(
                transfer=transfer,
                from_name=sender.full_name,
                to_name=recipient.full_name,
            )

    async def month_transfers(
        self, actor_vk_id: int, period: MonthPeriod
    ) -> list[TransferRow]:
        async with self._uow_factory() as uow:
            await self._require_collector(uow, actor_vk_id)
            transfers = await uow.transfers.list_for_month(period)
            return [await _transfer_row(uow, t) for t in transfers]

    async def delete_transfer(self, actor_vk_id: int, transfer_id: int) -> None:
        """Удаляет передачу — отдавший или администратор."""
        async with self._uow_factory() as uow:
            await self._require_collector(uow, actor_vk_id)
            transfer = await uow.transfers.get(transfer_id)
            if transfer is None:
                raise NotFoundError('Передача не найдена')
            await self._require_owner(
                uow, actor_vk_id, transfer.from_user_id, 'передачу'
            )
            await uow.transfers.delete(transfer_id)
            await record_action(
                uow,
                actor_vk_id,
                'transfer.delete',
                f'transfer_id={transfer_id} amount={transfer.amount}',
            )
            await uow.commit()

    # ─────────────────────────── корректировки ─────────────────────────

    async def add_adjustment(
        self,
        actor_vk_id: int,
        *,
        adjusted_on: date,
        target: str,
        amount: Decimal,
        reason: str,
    ) -> AdjustmentRow:
        """Корректирует остаток человека на сумму со знаком (только админ)."""
        _validate_money(amount)
        if amount == 0:
            raise ValidationError('Сумма корректировки не может быть нулевой')
        reason = _validate_text(reason, 'Причина', MAX_REASON_LEN)
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, actor_vk_id)
            user = await resolve_user(uow, target)
            adjustment = await uow.balance_adjustments.add(
                BalanceAdjustment(
                    adjusted_on=adjusted_on,
                    user_id=user.id,
                    amount=amount,
                    reason=reason,
                    created_by_vk_id=actor_vk_id,
                )
            )
            await record_action(
                uow,
                actor_vk_id,
                'balance_adjustment.add',
                f'adjustment_id={adjustment.id} user_id={user.id} '
                f'amount={amount} adjusted_on={adjusted_on}',
            )
            await uow.commit()
            return AdjustmentRow(
                adjustment=adjustment, user_name=user.full_name
            )

    async def adjustments_until(
        self, actor_vk_id: int, day: date
    ) -> list[AdjustmentRow]:
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, actor_vk_id)
            adjustments = await uow.balance_adjustments.list_until(day)
            return [await _adjustment_row(uow, a) for a in adjustments]

    async def delete_adjustment(
        self, actor_vk_id: int, adjustment_id: int
    ) -> None:
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, actor_vk_id)
            adjustment = await uow.balance_adjustments.get(adjustment_id)
            if adjustment is None:
                raise NotFoundError('Корректировка не найдена')
            await uow.balance_adjustments.delete(adjustment_id)
            await record_action(
                uow,
                actor_vk_id,
                'balance_adjustment.delete',
                f'adjustment_id={adjustment_id} amount={adjustment.amount}',
            )
            await uow.commit()

    # ───────────────────────────── права ───────────────────────────────

    async def _require_collector(self, uow: UnitOfWork, vk_id: int) -> None:
        await permissions.require_role(uow, self._vk, vk_id, RoleName.COLLECTOR)

    async def _resolve_account(
        self, uow: UnitOfWork, actor_vk_id: int, account: str | None
    ) -> User:
        """Владелец счёта: свой по умолчанию, чужой — только для админа."""
        own = await uow.users.get_by_vk_id(actor_vk_id)
        if account is None:
            if own is None:
                raise ValidationError(
                    'Вас нет в списке участников клуба — укажите, с чьего '
                    'счёта операция'
                )
            return own
        owner = await resolve_user(uow, account)
        if (
            own is None or owner.id != own.id
        ) and not await permissions.is_admin(uow, self._vk, actor_vk_id):
            raise PermissionDeniedError(
                'Сборщик записывает операции только со своего счёта'
            )
        return owner

    async def _require_owner(
        self, uow: UnitOfWork, actor_vk_id: int, owner_user_id: int, what: str
    ) -> None:
        """Чужую запись меняет только администратор."""
        own = await uow.users.get_by_vk_id(actor_vk_id)
        if own is not None and own.id == owner_user_id:
            return
        if await permissions.is_admin(uow, self._vk, actor_vk_id):
            return
        raise PermissionDeniedError(
            f'Изменить {what} с чужого счёта может только администратор'
        )


async def _get_expense_or_raise(uow: UnitOfWork, expense_id: int) -> Expense:
    expense = await uow.expenses.get(expense_id)
    if expense is None:
        raise NotFoundError('Расход не найден')
    return expense


async def _user_name(uow: UnitOfWork, user_id: int) -> str:
    user = await uow.users.get_by_id(user_id)
    return user.full_name if user else f'id{user_id}'


async def _expense_row(uow: UnitOfWork, expense: Expense) -> ExpenseRow:
    return ExpenseRow(
        expense=expense,
        account_name=await _user_name(uow, expense.account_user_id),
    )


async def _transfer_row(
    uow: UnitOfWork, transfer: AccountTransfer
) -> TransferRow:
    return TransferRow(
        transfer=transfer,
        from_name=await _user_name(uow, transfer.from_user_id),
        to_name=await _user_name(uow, transfer.to_user_id),
    )


async def _adjustment_row(
    uow: UnitOfWork, adjustment: BalanceAdjustment
) -> AdjustmentRow:
    return AdjustmentRow(
        adjustment=adjustment,
        user_name=await _user_name(uow, adjustment.user_id),
    )


def _validate_positive(amount: Decimal) -> None:
    _validate_money(amount)
    if amount <= 0:
        raise ValidationError('Сумма должна быть больше нуля')


def _validate_money(amount: Decimal) -> None:
    """Конечное число с точностью до копеек, влезающее в Numeric(12, 2)."""
    if not amount.is_finite() or amount != amount.quantize(_KOPECK):
        raise ValidationError('Сумма — число с точностью до копеек')
    if abs(amount) >= _MAX_AMOUNT:
        raise ValidationError('Слишком большая сумма')


def _validate_text(value: str, what: str, max_len: int) -> str:
    value = value.strip()
    if not value:
        raise ValidationError(f'{what} не может быть пустым')
    if len(value) > max_len:
        raise ValidationError(f'{what} длиннее {max_len} символов')
    return value


def _validate_note(note: str | None) -> None:
    if note is not None and len(note) > MAX_NOTE_LEN:
        raise ValidationError(f'Примечание длиннее {MAX_NOTE_LEN} символов')
