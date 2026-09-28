"""Остатки клубных денег на дату — у кого сколько на руках (вкладка «ОСТАТОК»).

Движения денег собираются из источников, которые уже есть в БД:

* оплаченные абонементы и разовые посещения — приход у сборщика
  (``collector_vk_id``) в день отметки оплаты (``marked_at`` в часовом
  поясе клуба): деньги на руках появляются тогда, когда их получили, а не
  в день тренировки;
* расходы, передачи и корректировки — ручные записи ``FinanceUseCases``.

Дальше — чистый расчёт ``domain.services.balance_calc.account_balances``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from avrora_bot.application.services import permissions
from avrora_bot.application.services.user_lookup import vk_id_label
from avrora_bot.domain.entities import Subscription
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import NotFoundError, ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway
from avrora_bot.domain.services.balance_calc import (
    AccountBalance,
    Movement,
    MovementKind,
    account_balances,
    manual_movements,
)

UowFactory = Callable[[], UnitOfWork]

# Оплата, у которой сборщик не записан (старые записи), — на отдельный
# «счёт», чтобы деньги не пропадали из итога. Настоящие id пользователей
# положительные, ключи ненайденных сборщиков — отрицательный vk_id.
UNKNOWN_COLLECTOR_ID = 0


@dataclass(frozen=True, slots=True)
class BalanceRow:
    """Остаток одного человека с разбивкой за период."""

    name: str
    balance: AccountBalance


@dataclass(frozen=True, slots=True)
class BalanceReport:
    """Остатки всех на ``end`` с разбивкой движений за ``[start, end]``."""

    start: date
    end: date
    rows: list[BalanceRow]

    @property
    def total(self) -> Decimal:
        """Сколько клубных денег на руках у всех вместе."""
        return sum((r.balance.closing for r in self.rows), Decimal(0))


class BalanceUseCases:
    """Расчёт остатков на дату."""

    def __init__(
        self, uow_factory: UowFactory, vk_gateway: VkGateway, tz: str
    ) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway
        self._tz = ZoneInfo(tz)

    def today(self) -> date:
        """Сегодняшняя дата в часовом поясе клуба."""
        return datetime.now(self._tz).date()

    async def balances(
        self, actor_vk_id: int, end: date, start: date | None = None
    ) -> BalanceReport:
        """Остатки всех на конец дня ``end`` (для сборщиков и админа).

        :param start: начало периода разбивки; по умолчанию — первое число
            месяца ``end``. Всё, что раньше, — в колонке «на начало».

        В отчёт попадают все, у кого были движения до ``end``, и все
        текущие сборщики — даже с нулём.
        """
        start = start or end.replace(day=1)
        if start > end:
            raise ValidationError('Начало периода позже его конца')
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            balances = account_balances(
                await self._movements(uow, end), start, end
            )
            for collector in await uow.roles.users_with_role(
                RoleName.COLLECTOR
            ):
                balances.setdefault(
                    collector.id, AccountBalance(user_id=collector.id)
                )
            rows = [
                BalanceRow(name=await _account_name(uow, user_id), balance=b)
                for user_id, b in balances.items()
            ]
        rows.sort(key=lambda r: r.name)
        return BalanceReport(start=start, end=end, rows=rows)

    async def my_balance(self, actor_vk_id: int, end: date) -> BalanceRow:
        """Свой остаток на ``end`` с разбивкой за месяц ``end``."""
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_vk_id(actor_vk_id)
        if user is None:
            raise NotFoundError('Вас нет в списке участников клуба')
        report = await self.balances(actor_vk_id, end)
        for row in report.rows:
            if row.balance.user_id == user.id:
                return row
        return BalanceRow(
            name=user.full_name, balance=AccountBalance(user_id=user.id)
        )

    async def _movements(self, uow: UnitOfWork, end: date) -> list[Movement]:
        until = self._end_of_day_utc(end)
        movements = list(
            manual_movements(
                await uow.expenses.list_until(end),
                await uow.transfers.list_until(end),
                await uow.balance_adjustments.list_until(end),
            )
        )
        accounts: dict[int | None, int] = {}
        subscriptions: dict[int, Subscription] = {}

        for payment in await uow.subscriptions.paid_payments_until(until):
            subscription = subscriptions.get(payment.subscription_id)
            if subscription is None:
                subscription = await uow.subscriptions.get(
                    payment.subscription_id
                )
                if subscription is None:
                    continue
                subscriptions[payment.subscription_id] = subscription
            movements.append(
                Movement(
                    user_id=await _collector_account(
                        uow, accounts, payment.collector_vk_id
                    ),
                    on=self._local_date(payment.marked_at),
                    kind=MovementKind.SUBSCRIPTION,
                    amount=payment.paid_amount(subscription),
                )
            )

        movements.extend(
            [
                Movement(
                    user_id=await _collector_account(
                        uow, accounts, visit.collector_vk_id
                    ),
                    on=self._local_date(visit.marked_at),
                    kind=MovementKind.ONE_TIME,
                    amount=visit.amount,
                )
                for visit in await uow.one_time.paid_visits_until(until)
            ]
        )
        return movements

    def _end_of_day_utc(self, day: date) -> datetime:
        """Конец дня ``day`` по часовому поясу клуба — в UTC."""
        local_end = datetime.combine(day + timedelta(days=1), time(), self._tz)
        return (local_end - timedelta(microseconds=1)).astimezone(UTC)

    def _local_date(self, moment: datetime | None) -> date:
        """Дата отметки оплаты в часовом поясе клуба.

        SQLite отдаёт ``DateTime(timezone=True)`` без tzinfo — хранится
        всегда UTC, поэтому naive-значение трактуется как UTC.
        """
        assert moment is not None  # paid_*_until отбирает только с marked_at
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone(self._tz).date()


async def _collector_account(
    uow: UnitOfWork, cache: dict[int | None, int], vk_id: int | None
) -> int:
    """Ключ «счёта» сборщика по его vk_id (с кэшем на один расчёт)."""
    if vk_id in cache:
        return cache[vk_id]
    if vk_id is None:
        key = UNKNOWN_COLLECTOR_ID
    else:
        user = await uow.users.get_by_vk_id(vk_id)
        key = user.id if user is not None and user.id is not None else -vk_id
    cache[vk_id] = key
    return key


async def _account_name(uow: UnitOfWork, key: int) -> str:
    if key == UNKNOWN_COLLECTOR_ID:
        return 'Сборщик не указан'
    if key < 0:
        return vk_id_label(-key)
    user = await uow.users.get_by_id(key)
    return user.full_name if user else f'id{key}'
