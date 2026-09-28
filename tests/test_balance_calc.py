"""Тесты расчёта остатков — сверка с вкладкой «ОСТАТОК» ``tmp/avrora.xlsx``."""

from datetime import date
from decimal import Decimal

from avrora_bot.domain.entities import (
    AccountTransfer,
    BalanceAdjustment,
    Expense,
)
from avrora_bot.domain.enums import ExpenseCategory
from avrora_bot.domain.services.balance_calc import (
    Movement,
    MovementKind,
    account_balances,
    manual_movements,
)

SEDOVA, RITA, SVETA, TEPLOVA = 1, 2, 3, 4
ADMIN_VK_ID = 100


def _adjustment(user_id: int, amount: str) -> BalanceAdjustment:
    return BalanceAdjustment(
        adjusted_on=date(2026, 8, 19),
        user_id=user_id,
        amount=Decimal(amount),
        reason='Остаток по таблице на 19.08.2026',
        created_by_vk_id=ADMIN_VK_ID,
    )


def _expense(day: int, amount: str, description: str) -> Expense:
    return Expense(
        spent_on=date(2026, 9, day),
        category=(
            ExpenseCategory.HALL
            if 'зала' in description
            else ExpenseCategory.COACH
        ),
        description=description,
        amount=Decimal(amount),
        account_user_id=SEDOVA,
        created_by_vk_id=ADMIN_VK_ID,
    )


def _income(
    user_id: int, day: int, amount: str, kind: MovementKind
) -> Movement:
    return Movement(
        user_id=user_id,
        on=date(2026, 9, day),
        kind=kind,
        amount=Decimal(amount),
    )


# Вкладка «РАСХОДЫ» за сентябрь 2026 — всё со счёта Ольги Седовой.
SEPTEMBER_EXPENSES = [
    _expense(1, '38750', 'Оплата зала сентябрь'),
    _expense(1, '1500', 'Оплата тренер Дмитрий'),
    _expense(3, '1500', 'Оплата тренер Дмитрий'),
    _expense(5, '3000', 'Оплата тренер Елена'),
    _expense(13, '6000', 'Оплата тренер Елена'),
    _expense(21, '4500', 'Оплата тренер Елена'),
    _expense(22, '1500', 'Оплата тренер Дмитрий'),
    _expense(22, '1500', 'Оплата тренер Елена'),
    _expense(24, '1500', 'Оплата тренер Дмитрий'),
    _expense(25, '1500', 'Оплата тренер Елена'),
]


def test_september_balances_match_spreadsheet() -> None:
    adjustments = [
        _adjustment(RITA, '5700'),
        _adjustment(SEDOVA, '1800'),
        _adjustment(SVETA, '870'),
    ]
    # «Сентябрь абонемент»: 24 × 2450 + 2100 = 60 900, всё собрала Седова.
    subscriptions = [
        _income(SEDOVA, 2, '2450', MovementKind.SUBSCRIPTION) for _ in range(24)
    ] + [_income(SEDOVA, 2, '2100', MovementKind.SUBSCRIPTION)]
    # «Сентябрь разовая»: у Риты 8 × 350 (в таблице SUMIF потерял строку
    # с пробелом в конце ФИО и показал 2450), у Тепловой 23 × 350 = 8050.
    one_time = [
        _income(RITA, 3, '350', MovementKind.ONE_TIME) for _ in range(8)
    ] + [_income(TEPLOVA, 4, '350', MovementKind.ONE_TIME) for _ in range(23)]

    movements = [
        *manual_movements(SEPTEMBER_EXPENSES, [], adjustments),
        *subscriptions,
        *one_time,
    ]
    balances = account_balances(
        movements, start=date(2026, 9, 1), end=date(2026, 9, 30)
    )

    sedova = balances[SEDOVA]
    assert sedova.opening == Decimal('1800')
    assert sedova.subscriptions == Decimal('60900')
    assert sedova.expenses == Decimal('61250')
    assert sedova.closing == Decimal('1450')  # как ОСТАТОК!B8

    assert balances[RITA].closing == Decimal('8500')  # в таблице 8150
    assert balances[SVETA].closing == Decimal('870')
    assert balances[TEPLOVA].closing == Decimal('8050')
    # В таблице ИТОГО = 10 470: SUM(B7:B9) не захватил строку Тепловой.
    assert sum(b.closing for b in balances.values()) == Decimal('18870')


def test_transfer_moves_money_between_accounts() -> None:
    transfer = AccountTransfer(
        transferred_on=date(2026, 9, 10),
        from_user_id=TEPLOVA,
        to_user_id=SEDOVA,
        amount=Decimal('1500'),
        created_by_vk_id=ADMIN_VK_ID,
    )
    movements = [
        _income(TEPLOVA, 4, '2000', MovementKind.ONE_TIME),
        *manual_movements([], [transfer], []),
    ]
    balances = account_balances(
        movements, start=date(2026, 9, 1), end=date(2026, 9, 30)
    )
    assert balances[TEPLOVA].transfers == Decimal('-1500')
    assert balances[TEPLOVA].closing == Decimal('500')
    assert balances[SEDOVA].transfers == Decimal('1500')
    assert balances[SEDOVA].closing == Decimal('1500')


def test_period_window_splits_opening_and_ignores_future() -> None:
    movements = [
        _income(SEDOVA, 1, '100', MovementKind.SUBSCRIPTION),
        _income(SEDOVA, 15, '200', MovementKind.SUBSCRIPTION),
        _income(SEDOVA, 20, '400', MovementKind.SUBSCRIPTION),
    ]
    balances = account_balances(
        movements, start=date(2026, 9, 10), end=date(2026, 9, 15)
    )
    sedova = balances[SEDOVA]
    assert sedova.opening == Decimal('100')
    assert sedova.subscriptions == Decimal('200')
    assert sedova.closing == Decimal('300')


def test_account_without_movements_until_end_is_absent() -> None:
    movements = [_income(RITA, 20, '350', MovementKind.ONE_TIME)]
    balances = account_balances(
        movements, start=date(2026, 9, 1), end=date(2026, 9, 15)
    )
    assert balances == {}
