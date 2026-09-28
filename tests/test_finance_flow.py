"""Тесты сценариев финансового учёта: расходы, передачи, корректировки."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from avrora_bot.adapters.database.seed import seed_reference_data
from avrora_bot.application.use_cases.finance import (
    FinanceUseCases,
    guess_category,
)
from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.domain.enums import ExpenseCategory, RoleName
from avrora_bot.domain.errors import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.value_objects import MonthPeriod
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1  # админ сообщества VK, в списке участников его нет
SEDOVA_VK_ID = 101
TEPLOVA_VK_ID = 102
PLAYER_VK_ID = 103
SEPTEMBER = MonthPeriod(2026, 9)
DAY = date(2026, 9, 5)


async def _prepare(uow_factory: Callable[[], UnitOfWork]) -> FinanceUseCases:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    async with uow_factory() as uow:
        await seed_reference_data(uow)
        await uow.commit()
    reg = RegistrationUseCases(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    for vk_id, name in [
        (SEDOVA_VK_ID, 'Седова Ольга'),
        (TEPLOVA_VK_ID, 'Теплова Ольга'),
        (PLAYER_VK_ID, 'Петрова Анна'),
    ]:
        await reg.self_register(RegistrationData(vk_id=vk_id, full_name=name))
        await reg.approve(ADMIN_VK_ID, vk_id)
    for vk_id in (SEDOVA_VK_ID, TEPLOVA_VK_ID):
        await roles.assign_role(ADMIN_VK_ID, vk_id, RoleName.COLLECTOR)
    return FinanceUseCases(uow_factory, vk)


async def _coach_expense(
    finance: FinanceUseCases, actor: int, account: str | None = None
) -> int:
    row = await finance.add_expense(
        actor,
        spent_on=DAY,
        category=ExpenseCategory.COACH,
        description='Оплата тренер Елена',
        amount=Decimal('3000'),
        account=account,
    )
    assert row.expense.id is not None
    return row.expense.id


@pytest.mark.asyncio
async def test_collector_records_expense_from_own_account(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    finance = await _prepare(uow_factory)
    expense_id = await _coach_expense(finance, SEDOVA_VK_ID)

    rows = await finance.month_expenses(TEPLOVA_VK_ID, SEPTEMBER)
    assert [(r.expense.id, r.account_name) for r in rows] == [
        (expense_id, 'Седова Ольга')
    ]
    assert (
        await finance.month_expenses(SEDOVA_VK_ID, MonthPeriod(2026, 10)) == []
    )


@pytest.mark.asyncio
async def test_collector_cannot_use_foreign_account(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    finance = await _prepare(uow_factory)
    with pytest.raises(PermissionDeniedError):
        await _coach_expense(finance, SEDOVA_VK_ID, account='Теплова')
    # Свой счёт, указанный явно, — можно.
    await _coach_expense(finance, SEDOVA_VK_ID, account=str(SEDOVA_VK_ID))


@pytest.mark.asyncio
async def test_player_cannot_record_expense(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    finance = await _prepare(uow_factory)
    with pytest.raises(PermissionDeniedError):
        await _coach_expense(finance, PLAYER_VK_ID)


@pytest.mark.asyncio
async def test_admin_without_profile_must_name_account(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    finance = await _prepare(uow_factory)
    with pytest.raises(ValidationError):
        await _coach_expense(finance, ADMIN_VK_ID)
    expense_id = await _coach_expense(finance, ADMIN_VK_ID, account='Теплова')
    row = await finance.get_expense(ADMIN_VK_ID, expense_id)
    assert row.account_name == 'Теплова Ольга'
    assert row.expense.created_by_vk_id == ADMIN_VK_ID


@pytest.mark.asyncio
async def test_edit_and_delete_only_own_expense(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    finance = await _prepare(uow_factory)
    expense_id = await _coach_expense(finance, SEDOVA_VK_ID)

    with pytest.raises(PermissionDeniedError):
        await finance.set_expense_amount(
            TEPLOVA_VK_ID, expense_id, Decimal('1')
        )
    with pytest.raises(PermissionDeniedError):
        await finance.delete_expense(TEPLOVA_VK_ID, expense_id)
    with pytest.raises(PermissionDeniedError):
        await finance.set_expense_account(SEDOVA_VK_ID, expense_id, 'Теплова')

    await finance.set_expense_date(SEDOVA_VK_ID, expense_id, date(2026, 9, 13))
    await finance.set_expense_amount(SEDOVA_VK_ID, expense_id, Decimal('6000'))
    await finance.set_expense_category(
        SEDOVA_VK_ID, expense_id, ExpenseCategory.OTHER
    )
    await finance.set_expense_description(SEDOVA_VK_ID, expense_id, '  Мячи  ')
    row = await finance.set_expense_note(SEDOVA_VK_ID, expense_id, 'чек у Оли')
    assert row.expense.spent_on == date(2026, 9, 13)
    assert row.expense.amount == Decimal('6000')
    assert row.expense.category is ExpenseCategory.OTHER
    assert row.expense.description == 'Мячи'
    assert row.expense.note == 'чек у Оли'

    moved = await finance.set_expense_account(
        ADMIN_VK_ID, expense_id, 'Теплова'
    )
    assert moved.account_name == 'Теплова Ольга'
    # Теперь расход на счёте Тепловой — править его может она, а не Седова.
    with pytest.raises(PermissionDeniedError):
        await finance.delete_expense(SEDOVA_VK_ID, expense_id)
    await finance.delete_expense(TEPLOVA_VK_ID, expense_id)
    with pytest.raises(NotFoundError):
        await finance.get_expense(SEDOVA_VK_ID, expense_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'amount', [Decimal('0'), Decimal('-5'), Decimal('1.005'), Decimal('NaN')]
)
async def test_expense_amount_validation(
    uow_factory: Callable[[], UnitOfWork], amount: Decimal
) -> None:
    finance = await _prepare(uow_factory)
    with pytest.raises(ValidationError):
        await finance.add_expense(
            SEDOVA_VK_ID,
            spent_on=DAY,
            category=ExpenseCategory.HALL,
            description='Оплата зала сентябрь',
            amount=amount,
        )


@pytest.mark.asyncio
async def test_expense_description_required(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    finance = await _prepare(uow_factory)
    with pytest.raises(ValidationError):
        await finance.add_expense(
            SEDOVA_VK_ID,
            spent_on=DAY,
            category=ExpenseCategory.HALL,
            description='   ',
            amount=Decimal('100'),
        )


@pytest.mark.asyncio
async def test_transfer_flow(uow_factory: Callable[[], UnitOfWork]) -> None:
    finance = await _prepare(uow_factory)
    row = await finance.add_transfer(
        TEPLOVA_VK_ID,
        transferred_on=DAY,
        to='Седова',
        amount=Decimal('1500'),
        note='на оплату тренера',
    )
    assert (row.from_name, row.to_name) == ('Теплова Ольга', 'Седова Ольга')

    rows = await finance.month_transfers(SEDOVA_VK_ID, SEPTEMBER)
    assert [r.transfer.id for r in rows] == [row.transfer.id]

    with pytest.raises(PermissionDeniedError):
        await finance.delete_transfer(SEDOVA_VK_ID, row.transfer.id)
    await finance.delete_transfer(TEPLOVA_VK_ID, row.transfer.id)
    assert await finance.month_transfers(SEDOVA_VK_ID, SEPTEMBER) == []


@pytest.mark.asyncio
async def test_transfer_restrictions(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    finance = await _prepare(uow_factory)
    with pytest.raises(ValidationError):
        await finance.add_transfer(
            SEDOVA_VK_ID, transferred_on=DAY, to='Седова', amount=Decimal('1')
        )
    with pytest.raises(PermissionDeniedError):
        await finance.add_transfer(
            SEDOVA_VK_ID,
            transferred_on=DAY,
            to='Седова',
            amount=Decimal('1'),
            source='Теплова',
        )
    # Администратор записывает передачу между любыми людьми.
    row = await finance.add_transfer(
        ADMIN_VK_ID,
        transferred_on=DAY,
        to='Седова',
        amount=Decimal('1'),
        source='Теплова',
    )
    assert row.transfer.created_by_vk_id == ADMIN_VK_ID


@pytest.mark.asyncio
async def test_adjustments_are_admin_only(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    finance = await _prepare(uow_factory)
    with pytest.raises(PermissionDeniedError):
        await finance.add_adjustment(
            SEDOVA_VK_ID,
            adjusted_on=date(2026, 8, 19),
            target='Седова',
            amount=Decimal('1800'),
            reason='Остаток по таблице',
        )
    with pytest.raises(ValidationError):
        await finance.add_adjustment(
            ADMIN_VK_ID,
            adjusted_on=date(2026, 8, 19),
            target='Седова',
            amount=Decimal('0'),
            reason='Остаток по таблице',
        )

    row = await finance.add_adjustment(
        ADMIN_VK_ID,
        adjusted_on=date(2026, 8, 19),
        target='Седова',
        amount=Decimal('-200'),
        reason='Расхождение с наличными',
    )
    listed = await finance.adjustments_until(ADMIN_VK_ID, date(2026, 9, 1))
    assert [(r.adjustment.id, r.user_name) for r in listed] == [
        (row.adjustment.id, 'Седова Ольга')
    ]
    with pytest.raises(PermissionDeniedError):
        await finance.adjustments_until(SEDOVA_VK_ID, date(2026, 9, 1))
    await finance.delete_adjustment(ADMIN_VK_ID, row.adjustment.id)
    assert await finance.adjustments_until(ADMIN_VK_ID, date(2026, 9, 1)) == []


@pytest.mark.parametrize(
    ('description', 'expected'),
    [
        ('Оплата зала сентябрь', ExpenseCategory.HALL),
        ('Оплата тренер Дмитрий', ExpenseCategory.COACH),
        ('Мячи', ExpenseCategory.OTHER),
    ],
)
def test_guess_category(description: str, expected: ExpenseCategory) -> None:
    assert guess_category(description) is expected
