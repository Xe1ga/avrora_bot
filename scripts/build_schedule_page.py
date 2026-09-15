#!/usr/bin/env python
"""Генерирует docs/schedule.html из реальных данных ``calendar_events``.

Запуск вручную, когда нужно опубликовать актуальное расписание::

    uv run python scripts/build_schedule_page.py
    uv run python scripts/build_schedule_page.py --months 2026-09 2026-11

Без ``--months`` берутся текущий и следующий календарные месяцы (по
часовому поясу из настроек, ``TZ`` в ``.env``).

Файл ``docs/schedule.html`` полностью перезаписывается при каждом
запуске — редактировать его руками бессмысленно, следующий запуск сотрёт
правки. Меняйте данные через бота (команда «событие <дата> <тип> <время>
<место>» / «удалить событие <id>», см. «🗓 Календарь: команды») и
перезапускайте этот скрипт.

Данные берутся исключительно из таблицы ``calendar_events`` — никаких
предположений о «регулярном» расписании скрипт не делает: если событие не
занесено в календарь бота, на странице его не будет.

Требует доступа к той же БД, что и сам бот (переменные окружения из ``.env``
в корне проекта — DSN, ключ шифрования ПД для сборки Unit of Work; сами
события календаря не шифруются и в расшифровке не нуждаются).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(
    0, str(REPO_ROOT / 'src')
)  # на случай запуска без editable-install

from avrora_bot.adapters.database.crypto import (  # noqa: E402
    PiiCipher,
    decode_pii_key,
)
from avrora_bot.adapters.database.engine import (  # noqa: E402
    create_engine,
    create_session_factory,
)
from avrora_bot.adapters.database.unit_of_work import (  # noqa: E402
    SqlAlchemyUnitOfWork,
)
from avrora_bot.config import get_settings  # noqa: E402
from avrora_bot.domain.entities import CalendarEvent  # noqa: E402
from avrora_bot.domain.errors import ValidationError  # noqa: E402
from avrora_bot.domain.value_objects import MonthPeriod  # noqa: E402

OUTPUT_PATH = REPO_ROOT / 'docs' / 'schedule.html'
TEMPLATE_PATH = Path(__file__).resolve().parent / 'schedule_template.html'

_TYPE_LABELS = {'training': '🏐 Тренировка', 'game': '🏆 Игра'}
# Событиям без времени — место в конце дня при сортировке.
_NO_TIME_SORT_KEY = '99:99'


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Парсит аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description='Генерирует docs/schedule.html из calendar_events.'
    )
    parser.add_argument(
        '--months',
        nargs='+',
        metavar='YYYY-MM',
        help=(
            'Месяцы для отображения на странице, напр. --months 2026-09 '
            '2026-11. По умолчанию — текущий и следующий календарные месяцы.'
        ),
    )
    return parser.parse_args(argv)


def resolve_months(raw: list[str] | None, tz_name: str) -> list[MonthPeriod]:
    """Строит отсортированный список уникальных периодов без дублей.

    Без ``raw`` — текущий и следующий месяц по часовому поясу ``tz_name``.
    """
    if raw:
        try:
            periods = [MonthPeriod.parse(m) for m in raw]
        except ValidationError as exc:
            print(f'Ошибка: {exc}', file=sys.stderr)
            raise SystemExit(1) from exc
    else:
        today = datetime.now(ZoneInfo(tz_name)).date()
        current = MonthPeriod.from_date(today)
        if current.month == 12:  # noqa: PLR2004
            next_period = MonthPeriod(current.year + 1, 1)
        else:
            next_period = MonthPeriod(current.year, current.month + 1)
        periods = [current, next_period]

    seen: set[str] = set()
    unique: list[MonthPeriod] = []
    for period in periods:
        key = str(period)
        if key not in seen:
            seen.add(key)
            unique.append(period)
    unique.sort(key=str)
    return unique


async def fetch_events(periods: list[MonthPeriod]) -> list[CalendarEvent]:
    """Забирает реальные события calendar_events за все запрошенные месяцы."""
    settings = get_settings()
    engine = create_engine(settings.database_dsn)
    session_factory = create_session_factory(engine)
    cipher = PiiCipher(
        decode_pii_key(settings.pii_encryption_key.get_secret_value())
    )

    events: list[CalendarEvent] = []
    try:
        async with SqlAlchemyUnitOfWork(session_factory, cipher) as uow:
            for period in periods:
                events.extend(await uow.calendar.list_for_month(period))
    finally:
        await engine.dispose()

    events.sort(key=_sort_key)
    return events


def _sort_key(event: CalendarEvent) -> tuple[date, str]:
    time_key = (
        event.event_time.strftime('%H:%M')
        if event.event_time
        else _NO_TIME_SORT_KEY
    )
    return (event.event_date, time_key)


def event_to_dict(event: CalendarEvent) -> dict[str, str | None]:
    """Сериализует событие в JSON-совместимый словарь для страницы."""
    return {
        'date': event.event_date.isoformat(),
        'time': event.event_time.strftime('%H:%M')
        if event.event_time
        else None,
        'type': event.event_type.value,
        'place': event.place,
        'comment': event.comment,
    }


def month_tabs_html(periods: list[MonthPeriod]) -> str:
    """HTML вкладок-фильтров по месяцам: «Все» + одна на каждый период."""
    buttons = [
        '<button class="tab" type="button" data-month="all" '
        'aria-pressed="true">Все</button>'
    ]
    for period in periods:
        label = period.label().capitalize()
        buttons.append(
            f'<button class="tab" type="button" data-month="{period}" '
            f'aria-pressed="false">{label}</button>'
        )
    return '\n        '.join(buttons)


def months_subtitle(periods: list[MonthPeriod]) -> str:
    """Строка подзаголовка, напр. «сентябрь–октябрь 2026» или «сентябрь 2026»."""
    if not periods:
        return 'нет данных'
    if len(periods) == 1:
        return periods[0].label()
    first, last = periods[0], periods[-1]
    if first.year == last.year:
        first_name = first.label().split(' ')[0]
        return f'{first_name}–{last.label()}'
    return f'{first.label()} – {last.label()}'


def build_html(periods: list[MonthPeriod], events: list[CalendarEvent]) -> str:
    """Собирает итоговый HTML, подставляя данные в шаблон страницы."""
    template = TEMPLATE_PATH.read_text(encoding='utf-8')
    events_json = json.dumps(
        [event_to_dict(e) for e in events], ensure_ascii=False, indent=2
    )
    generated = date.today().strftime('%d.%m.%Y')
    return (
        template.replace('__MONTH_TABS__', month_tabs_html(periods))
        .replace('__SUBTITLE__', months_subtitle(periods))
        .replace('__GENERATED_DATE__', generated)
        .replace('__EVENTS_JSON__', events_json)
    )


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    periods = resolve_months(args.months, settings.tz)
    print(f'Периоды: {", ".join(str(p) for p in periods)}')

    events = await fetch_events(periods)
    print(f'Событий получено из calendar_events: {len(events)}')
    if not events:
        print(
            'Внимание: событий не найдено — если куратор не заносит '
            'регулярные тренировки в календарь бота (команда «событие …»), '
            'страница будет показывать только то, что реально добавлено.'
        )

    html = build_html(periods, events)
    OUTPUT_PATH.write_text(html, encoding='utf-8')
    print(f'Записано: {OUTPUT_PATH}')


if __name__ == '__main__':
    asyncio.run(main())
