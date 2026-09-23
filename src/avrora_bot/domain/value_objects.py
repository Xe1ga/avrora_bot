"""Доменные объекты-значения (value objects)."""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal

from avrora_bot.domain.errors import ValidationError

# Денежные суммы храним и считаем в Decimal (никакого float).
RUBLE = Decimal('1')

_MONTH_NAMES_RU = (
    'январь',
    'февраль',
    'март',
    'апрель',
    'май',
    'июнь',
    'июль',
    'август',
    'сентябрь',
    'октябрь',
    'ноябрь',
    'декабрь',
)

_MIN_YEAR = 2000
_MAX_YEAR = 2100


def round_up_to_ruble(amount: Decimal) -> Decimal:
    """Округляет сумму вверх до целого рубля (ТЗ 3.2, п.2)."""
    return amount.quantize(RUBLE, rounding=ROUND_CEILING)


@dataclass(frozen=True, slots=True)
class MonthPeriod:
    """Расчётный период — конкретный месяц конкретного года."""

    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:  # noqa: PLR2004
            raise ValidationError(f'Некорректный месяц: {self.month}')
        if not _MIN_YEAR <= self.year <= _MAX_YEAR:
            raise ValidationError(f'Некорректный год: {self.year}')

    @classmethod
    def from_date(cls, value: date) -> MonthPeriod:
        """Строит период из даты."""
        return cls(year=value.year, month=value.month)

    @classmethod
    def parse(cls, raw: str) -> MonthPeriod:
        """Разбирает строку вида ``YYYY-MM`` или ``MM.YYYY``."""
        raw = raw.strip()
        if '-' in raw:
            year_s, month_s = raw.split('-', 1)
        elif '.' in raw:
            month_s, year_s = raw.split('.', 1)
        else:
            raise ValidationError(
                f'Не удалось разобрать период: {raw!r} (ожидается YYYY-MM)'
            )
        try:
            return cls(year=int(year_s), month=int(month_s))
        except ValueError as exc:
            raise ValidationError(f'Некорректный период: {raw!r}') from exc

    @property
    def days_in_month(self) -> int:
        """Число дней в месяце."""
        return calendar.monthrange(self.year, self.month)[1]

    @property
    def first_day(self) -> date:
        """Первый день месяца."""
        return date(self.year, self.month, 1)

    @property
    def last_day(self) -> date:
        """Последний день месяца."""
        return date(self.year, self.month, self.days_in_month)

    @property
    def month_name(self) -> str:
        """Название месяца по-русски в именительном падеже ('сентябрь')."""
        return _MONTH_NAMES_RU[self.month - 1]

    def next_month(self) -> MonthPeriod:
        """Следующий месяц (декабрь -> январь следующего года)."""
        if self.month == 12:  # noqa: PLR2004
            return MonthPeriod(year=self.year + 1, month=1)
        return MonthPeriod(year=self.year, month=self.month + 1)

    def label(self) -> str:
        """Человекочитаемая метка, напр. 'сентябрь 2026'."""
        return f'{self.month_name} {self.year}'

    def __str__(self) -> str:
        return f'{self.year:04d}-{self.month:02d}'
