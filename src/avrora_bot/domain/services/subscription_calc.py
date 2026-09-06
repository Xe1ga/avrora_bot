"""Расчёт суммы абонемента на человека."""

from decimal import Decimal

from avrora_bot.domain.errors import ValidationError
from avrora_bot.domain.value_objects import round_up_to_ruble


def per_person(total: Decimal, voters: int) -> Decimal:
    """Делит общую сумму сбора на число проголосовавших.

    Округляет результат вверх до целого рубля (ТЗ 3.2, п.2). Итоговое
    решение по сумме принимает сборщик — он может переопределить это
    значение вручную (см. ``application/use_cases/subscriptions.py``).

    :raises ValidationError: если число проголосовавших не положительно.
    """
    if voters <= 0:
        raise ValidationError('Число проголосовавших должно быть положительным')
    return round_up_to_ruble(total / Decimal(voters))
