"""Расчёт остатков клубных денег по «счетам» — людям, у которых они на руках.

Остаток человека на дату (вкладка «ОСТАТОК» ручной таблицы клуба)::

    корректировки + собрал (абонементы + разовые) − расходы ± передачи

Все движения денег приводятся к ``Movement`` — сумма со знаком на счёте
конкретного человека в конкретный день; дальше это чистое суммирование.
Движения до ``start`` сворачиваются в остаток на начало, движения в
``[start, end]`` раскладываются по видам, более поздние не учитываются.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from avrora_bot.domain.entities import (
    AccountTransfer,
    BalanceAdjustment,
    Expense,
)

_ZERO = Decimal(0)


class MovementKind(StrEnum):
    """Вид движения денег — колонка разбивки в отчёте об остатках."""

    SUBSCRIPTION = 'subscription'  # собран абонемент
    ONE_TIME = 'one_time'  # собрано разовое посещение
    EXPENSE = 'expense'  # расход
    TRANSFER = 'transfer'  # передача другому человеку / от другого
    ADJUSTMENT = 'adjustment'  # ручная корректировка / начальный остаток


@dataclass(frozen=True, slots=True)
class Movement:
    """Движение денег на счёте человека: «+» — пришло, «−» — ушло."""

    user_id: int
    on: date
    kind: MovementKind
    amount: Decimal


@dataclass(slots=True)
class AccountBalance:
    """Остаток на счёте человека с разбивкой за период ``[start, end]``.

    ``expenses`` — положительное число (сколько потрачено), остальные
    поля — суммы со знаком, как они меняют остаток.
    """

    user_id: int
    opening: Decimal = _ZERO
    subscriptions: Decimal = _ZERO
    one_time: Decimal = _ZERO
    expenses: Decimal = _ZERO
    transfers: Decimal = _ZERO
    adjustments: Decimal = _ZERO

    @property
    def closing(self) -> Decimal:
        """Остаток на конец периода."""
        return (
            self.opening
            + self.subscriptions
            + self.one_time
            - self.expenses
            + self.transfers
            + self.adjustments
        )

    def apply(self, movement: Movement) -> None:
        """Относит движение внутри периода к колонке его вида."""
        match movement.kind:
            case MovementKind.SUBSCRIPTION:
                self.subscriptions += movement.amount
            case MovementKind.ONE_TIME:
                self.one_time += movement.amount
            case MovementKind.EXPENSE:
                self.expenses -= movement.amount
            case MovementKind.TRANSFER:
                self.transfers += movement.amount
            case MovementKind.ADJUSTMENT:
                self.adjustments += movement.amount


def expense_movement(expense: Expense) -> Movement:
    """Расход уменьшает остаток того, с чьих денег оплачено."""
    return Movement(
        user_id=expense.account_user_id,
        on=expense.spent_on,
        kind=MovementKind.EXPENSE,
        amount=-expense.amount,
    )


def transfer_movements(transfer: AccountTransfer) -> tuple[Movement, Movement]:
    """Передача — минус у отдавшего и плюс у получившего."""
    return (
        Movement(
            user_id=transfer.from_user_id,
            on=transfer.transferred_on,
            kind=MovementKind.TRANSFER,
            amount=-transfer.amount,
        ),
        Movement(
            user_id=transfer.to_user_id,
            on=transfer.transferred_on,
            kind=MovementKind.TRANSFER,
            amount=transfer.amount,
        ),
    )


def adjustment_movement(adjustment: BalanceAdjustment) -> Movement:
    """Корректировка — сумма со знаком как есть."""
    return Movement(
        user_id=adjustment.user_id,
        on=adjustment.adjusted_on,
        kind=MovementKind.ADJUSTMENT,
        amount=adjustment.amount,
    )


def manual_movements(
    expenses: Iterable[Expense],
    transfers: Iterable[AccountTransfer],
    adjustments: Iterable[BalanceAdjustment],
) -> Iterator[Movement]:
    """Движения из расходов, передач и корректировок (без сборов)."""
    for expense in expenses:
        yield expense_movement(expense)
    for transfer in transfers:
        yield from transfer_movements(transfer)
    for adjustment in adjustments:
        yield adjustment_movement(adjustment)


def account_balances(
    movements: Iterable[Movement], start: date, end: date
) -> dict[int, AccountBalance]:
    """Остатки по людям на ``end`` с разбивкой движений за ``[start, end]``.

    В результат попадают все, у кого было хоть одно движение не позже
    ``end`` — в том числе с нулевым остатком (кто и сколько через себя
    провёл, видно по разбивке).
    """
    balances: dict[int, AccountBalance] = {}
    for movement in movements:
        if movement.on > end:
            continue
        balance = balances.setdefault(
            movement.user_id, AccountBalance(user_id=movement.user_id)
        )
        if movement.on < start:
            balance.opening += movement.amount
        else:
            balance.apply(movement)
    return balances
