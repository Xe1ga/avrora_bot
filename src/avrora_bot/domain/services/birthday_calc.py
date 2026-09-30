"""Расчёт ближайшего дня рождения и дат напоминаний.

Правила (согласованы с заказчиком):

* напоминание заранее — за ``REMIND_DAYS_BEFORE`` дней; если подписка
  оформлена позже (до ДР осталось меньше), напоминание уходит сразу;
* напоминание в сам день рождения;
* в последний день месяца — сводка именинников следующего месяца;
* родившиеся 29 февраля в невисокосный год отмечают 28 февраля.
"""

import calendar
from datetime import date

REMIND_DAYS_BEFORE = 10

_FEBRUARY = 2
_LEAP_DAY = 29


def birthday_in_year(birthdate: date, year: int) -> date:
    """Дата дня рождения в заданном году (29.02 → 28.02 вне високосного)."""
    if (
        birthdate.month == _FEBRUARY
        and birthdate.day == _LEAP_DAY
        and not calendar.isleap(year)
    ):
        return date(year, _FEBRUARY, _LEAP_DAY - 1)
    return date(year, birthdate.month, birthdate.day)


def next_birthday(birthdate: date, today: date) -> date:
    """Ближайший день рождения не раньше ``today`` (сегодняшний — тоже)."""
    this_year = birthday_in_year(birthdate, today.year)
    if this_year >= today:
        return this_year
    return birthday_in_year(birthdate, today.year + 1)


def turning_age(birthdate: date, occasion: date) -> int:
    """Сколько лет исполняется в день рождения ``occasion``."""
    return occasion.year - birthdate.year


def is_last_day_of_month(day: date) -> bool:
    """``True``, если ``day`` — последний день своего месяца."""
    return day.day == calendar.monthrange(day.year, day.month)[1]


def is_next_month(occasion: date, today: date) -> bool:
    """``True``, если ``occasion`` приходится на следующий за ``today`` месяц."""
    months = occasion.year * 12 + occasion.month
    return months - (today.year * 12 + today.month) == 1
