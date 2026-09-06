"""Вспомогательные функции для VK-хендлеров: парсинг ввода и форматирование."""

from datetime import date, time
from decimal import Decimal, InvalidOperation

from avrora_bot.domain.errors import ValidationError
from avrora_bot.domain.value_objects import MonthPeriod

# Границы валидации роста, см.
_MIN_HEIGHT = 100
_MAX_HEIGHT = 250


def parse_birthdate(raw: str) -> date:
    """Разбирает дату рождения формата ДД.ММ.ГГГГ."""
    parts = raw.strip().split('.')
    if len(parts) != 3:  # noqa: PLR2004
        raise ValidationError('Формат даты: ДД.ММ.ГГГГ')
    try:
        day, month, year = (int(p) for p in parts)
        return date(year, month, day)
    except ValueError as exc:
        raise ValidationError('Некорректная дата') from exc


def parse_height(raw: str) -> int:
    """Разбирает рост в сантиметрах."""
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValidationError('Рост — число в сантиметрах') from exc
    if not _MIN_HEIGHT <= value <= _MAX_HEIGHT:
        raise ValidationError('Рост должен быть в пределах 100–250 см')
    return value


def parse_period(raw: str) -> MonthPeriod:
    """Разбирает период (YYYY-MM или MM.YYYY)."""
    return MonthPeriod.parse(raw)


def parse_vk_ids(raw: str) -> list[int]:
    """Разбирает список vk_id из многострочного/через-запятую текста."""
    tokens = raw.replace(',', '\n').split('\n')
    ids: list[int] = []
    for raw_token in tokens:
        token = raw_token.strip()
        if not token:
            continue
        try:
            ids.append(int(token))
        except ValueError as exc:
            raise ValidationError(
                f'Ожидаются числовые vk_id, получено: {token!r}'
            ) from exc
    if not ids:
        raise ValidationError('Список пуст')
    return ids


def parse_event_time(raw: str) -> time | None:
    """Разбирает время ЧЧ:ММ; пустая строка/«-» → None."""
    raw = raw.strip()
    if raw in ('', '-'):
        return None
    parts = raw.split(':')
    if len(parts) != 2:  # noqa: PLR2004
        raise ValidationError('Формат времени: ЧЧ:ММ')
    try:
        return time(int(parts[0]), int(parts[1]))
    except ValueError as exc:
        raise ValidationError('Некорректное время') from exc


def parse_amount(raw: str) -> Decimal:
    """Разбирает денежную сумму (запятая или точка как разделитель)."""
    try:
        return Decimal(raw.strip().replace(',', '.'))
    except InvalidOperation as exc:
        raise ValidationError('Сумма должна быть числом') from exc
