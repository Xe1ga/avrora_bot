"""Тесты доменных расчётов — сверка с «Оплата абонементов.md»."""

from datetime import time
from decimal import Decimal

import pytest

from avrora_bot.domain.entities import ScheduleSlot
from avrora_bot.domain.enums import Weekday
from avrora_bot.domain.errors import ValidationError
from avrora_bot.domain.services.subscription_calc import per_person
from avrora_bot.domain.services.tariff_calc import month_cost
from avrora_bot.domain.value_objects import MonthPeriod, round_up_to_ruble

HALL_RATE = Decimal('1250')
COACH_RATE = Decimal('1500')

SCHEDULE = [
    ScheduleSlot(weekday=Weekday.TUESDAY, start=time(19, 0), end=time(20, 30)),
    ScheduleSlot(weekday=Weekday.TUESDAY, start=time(20, 30), end=time(22, 0)),
    ScheduleSlot(
        weekday=Weekday.THURSDAY, start=time(19, 30), end=time(21, 30)
    ),
    ScheduleSlot(weekday=Weekday.FRIDAY, start=time(19, 0), end=time(21, 0)),
]

# (year, month): (trainings, hall_hours, hall_sum, coach_sum, total)
REFERENCE = {
    (2026, 9): (18, 31, 38750, 27000, 65750),
    (2026, 10): (18, 32, 40000, 27000, 67000),
    (2026, 11): (16, 28, 35000, 24000, 59000),
    (2026, 12): (19, 33, 41250, 28500, 69750),
    (2027, 1): (17, 30, 37500, 25500, 63000),
    (2027, 2): (16, 28, 35000, 24000, 59000),
    (2027, 3): (18, 31, 38750, 27000, 65750),
    (2027, 4): (18, 32, 40000, 27000, 67000),
    (2027, 5): (16, 28, 35000, 24000, 59000),
}


@pytest.mark.parametrize(('period', 'expected'), list(REFERENCE.items()))
def test_month_cost_matches_reference(
    period: tuple[int, int], expected: tuple[int, ...]
) -> None:
    cost = month_cost(MonthPeriod(*period), SCHEDULE, HALL_RATE, COACH_RATE)
    trainings, hall_hours, hall_sum, coach_sum, total = expected
    assert cost.trainings == trainings
    assert int(cost.hall_hours) == hall_hours
    assert int(cost.hall_sum) == hall_sum
    assert int(cost.coach_sum) == coach_sum
    assert int(cost.total) == total


def test_per_person_rounds_up() -> None:
    # 65750 / 27 = 2435.18… → округление вверх до рубля.
    assert per_person(Decimal('65750'), 27) == Decimal('2436')


def test_per_person_exact_division() -> None:
    assert per_person(Decimal('60000'), 30) == Decimal('2000')


def test_per_person_rejects_non_positive_voters() -> None:
    with pytest.raises(ValidationError):
        per_person(Decimal('1000'), 0)


def test_round_up_to_ruble() -> None:
    assert round_up_to_ruble(Decimal('2435.01')) == Decimal('2436')
    assert round_up_to_ruble(Decimal('2435.00')) == Decimal('2435')


def test_month_period_parse_and_label() -> None:
    assert MonthPeriod.parse('2026-09') == MonthPeriod(2026, 9)
    assert MonthPeriod.parse('09.2026') == MonthPeriod(2026, 9)
    assert MonthPeriod(2026, 9).label() == 'сентябрь 2026'


def test_month_period_invalid() -> None:
    with pytest.raises(ValidationError):
        MonthPeriod(2026, 13)
