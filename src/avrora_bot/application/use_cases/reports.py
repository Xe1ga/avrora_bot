"""Формирование отчётов по месяцу (ТЗ 3.2 п.5-6).

Краткая сводка — текст для чата (✅/❌ + итоги). XLSX-отчёты генерирует
адаптер ``reports`` (см. ``adapters/vk/handlers/reports.py``).
"""

from collections.abc import Callable

from avrora_bot.application.use_cases.subscriptions import (
    MonthSummary,
    SubscriptionUseCases,
)
from avrora_bot.domain.enums import PaymentStatus
from avrora_bot.domain.ports.uow import UnitOfWork
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
