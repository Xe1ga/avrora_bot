"""Вспомогательные функции для VK-хендлеров: парсинг ввода и форматирование."""

from datetime import date, time
from decimal import Decimal, InvalidOperation

from avrora_bot.domain.errors import ValidationError
from avrora_bot.domain.value_objects import MonthPeriod

# Границы валидации роста, см.
_MIN_HEIGHT = 100
_MAX_HEIGHT = 250

# Лимит длины одного сообщения ВК — с запасом от 4096.
MAX_MESSAGE_LEN = 4000


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


def parse_visit_date(raw: str, today: date) -> date:
    """Дата посещения: ДД.ММ.ГГГГ; пустая строка/«сегодня» — ``today``."""
    if raw.strip().lower() in ('', 'сегодня'):
        return today
    return parse_birthdate(raw)


def split_message(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    """Режет длинный текст по строкам на части не длиннее ``limit``.

    ВК не принимает сообщения длиннее 4096 символов; резать посреди строки
    нельзя — запись списка развалится, поэтому граница всегда на переводе
    строки. Одна строка длиннее ``limit`` (в списках такого не бывает)
    остаётся отдельной частью как есть.
    """
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.split('\n'):
        # +1 — символ перевода строки между строками в части.
        added = len(line) + (1 if current else 0)
        if current and size + added > limit:
            parts.append('\n'.join(current))
            current, size, added = [], 0, len(line)
        current.append(line)
        size += added
    parts.append('\n'.join(current))
    return parts


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


def parse_targets(raw: str) -> list[str]:
    """Разбирает список vk_id/ФИО из многострочного/через-запятую текста.

    Элементы не приводятся к ``int`` — каждый может быть как vk_id, так и
    (частью) ФИО; итоговое разрешение делает
    ``application.services.user_lookup.resolve_user``/``resolve_users``.
    """
    tokens = raw.replace(',', '\n').split('\n')
    targets = [token.strip() for token in tokens if token.strip()]
    if not targets:
        raise ValidationError('Список пуст')
    return targets


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


def parse_optional(raw: str) -> str | None:
    """Пустая строка/«-» → ``None``, иначе — обрезанный текст как есть."""
    stripped = raw.strip()
    return None if stripped in ('', '-') else stripped


def parse_optional_birthdate(raw: str) -> date | None:
    """Как ``parse_birthdate``, но пустая строка/«-» очищают значение."""
    value = parse_optional(raw)
    return None if value is None else parse_birthdate(value)


def parse_optional_height(raw: str) -> int | None:
    """Как ``parse_height``, но пустая строка/«-» очищают значение."""
    value = parse_optional(raw)
    return None if value is None else parse_height(value)
