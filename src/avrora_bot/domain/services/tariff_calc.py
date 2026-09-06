"""Расчёт стоимости месяца из недельного расписания и тарифов.

Логика соответствует файлу «Оплата абонементов.md»: по шаблону недельного
расписания (``ScheduleSlot``) и календарю конкретного месяца считаются число
тренировок и суммарные часы зала, затем — суммы за зал и тренера.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from avrora_bot.domain.entities import ScheduleSlot
from avrora_bot.domain.enums import weekday_from_index
from avrora_bot.domain.value_objects import MonthPeriod


@dataclass(frozen=True, slots=True)
class MonthCost:
    """Результат расчёта стоимости месяца."""

    trainings: int  # число тренировок за месяц
    hall_hours: Decimal  # суммарные часы зала за месяц
    hall_sum: Decimal  # стоимость зала
    coach_sum: Decimal  # стоимость тренера
    total: Decimal  # итог


def _iter_month_days(period: MonthPeriod):
    """Генерирует все даты указанного месяца."""
    day = period.first_day
    last = period.last_day
    while day <= last:
        yield day
        day += timedelta(days=1)


def month_cost(
    period: MonthPeriod,
    schedule: list[ScheduleSlot],
    hall_hour_rate: Decimal,
    coach_session_rate: Decimal,
) -> MonthCost:
    """Считает стоимость месяца.

    :param period: расчётный месяц.
    :param schedule: активные слоты недельного расписания.
    :param hall_hour_rate: стоимость зала за час.
    :param coach_session_rate: стоимость одной тренировки с тренером.
    """
    active = [slot for slot in schedule if slot.active]
    # Группируем слоты по индексу дня недели для быстрого поиска.
    by_weekday: dict[int, list[ScheduleSlot]] = {}
    for slot in active:
        by_weekday.setdefault(slot.weekday.index, []).append(slot)

    trainings = 0
    hall_hours = Decimal(0)
    for day in _iter_month_days(period):
        slots = by_weekday.get(day.weekday())
        if not slots:
            continue
        for slot in slots:
            # Каждый слот расписания = одна тренировка.
            trainings += 1
            hall_hours += slot.hall_hours

    hall_sum = hall_hours * hall_hour_rate
    coach_sum = Decimal(trainings) * coach_session_rate
    total = hall_sum + coach_sum
    return MonthCost(
        trainings=trainings,
        hall_hours=hall_hours,
        hall_sum=hall_sum,
        coach_sum=coach_sum,
        total=total,
    )


def weekday_from_date_index(index: int):
    """Реэкспорт для удобства слоя приложения."""
    return weekday_from_index(index)
