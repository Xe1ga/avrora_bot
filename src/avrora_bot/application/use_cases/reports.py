"""Формирование отчётов по месяцу (ТЗ 3.2 п.5-6).

Краткая сводка — текст для чата (✅/❌ + итоги). Полный отчёт — XLSX,
генерируется адаптером ``reports`` и отправляется документом.
"""

from collections.abc import Callable
from decimal import Decimal

from avrora_bot.application.use_cases.subscriptions import (
    MonthSummary,
    SubscriptionUseCases,
)
from avrora_bot.domain.enums import PaymentStatus, TariffKind
from avrora_bot.domain.errors import NotFoundError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.services.tariff_calc import month_cost
from avrora_bot.domain.value_objects import MonthPeriod

UowFactory = Callable[[], UnitOfWork]


class ReportUseCases:
    """Текстовая сводка и данные для XLSX-отчёта."""

    def __init__(
        self, uow_factory: UowFactory, subscriptions: SubscriptionUseCases
    ) -> None:
        self._uow_factory = uow_factory
        self._subs = subscriptions

    async def text_summary(self, period: MonthPeriod) -> str:
        """Краткая текстовая сводка по месяцу для чата."""
        summary = await self._subs.month_summary(period)
        return _render_text_summary(period, summary)

    async def month_financials(
        self, period: MonthPeriod
    ) -> tuple[Decimal, Decimal]:
        """Возвращает суммы к переводу: (за зал, тренеру) за месяц.

        :raises NotFoundError: если тарифы месяца не заданы.
        """
        async with self._uow_factory() as uow:
            hall = await uow.tariffs.active_for(
                TariffKind.HALL_HOUR, period.first_day
            )
            coach = await uow.tariffs.active_for(
                TariffKind.COACH_SESSION, period.first_day
            )
            if hall is None or coach is None:
                raise NotFoundError('Не заданы тарифы на этот месяц')
            schedule = await uow.schedule.active_slots()
            cost = month_cost(period, schedule, hall.amount, coach.amount)
            return cost.hall_sum, cost.coach_sum


def _render_text_summary(period: MonthPeriod, summary: MonthSummary) -> str:
    """Собирает текст краткой сводки."""
    lines = [f'📋 Отчёт за {period.label()}', '']
    for row in summary.rows:
        mark = '✅' if row.status is PaymentStatus.PAID else '❌'
        lines.append(f'{mark} {row.user.full_name}')
    total = len(summary.rows)
    lines.extend(
        [
            '',
            f'Оплатили: {summary.paid_count} из {total}',
            f'Сумма абонемента: {summary.subscription.effective_amount} ₽',
            f'Собрано: {summary.collected} ₽',
        ]
    )
    return '\n'.join(lines)
