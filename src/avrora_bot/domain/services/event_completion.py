"""Момент окончания события календаря — для автоперевода в «выполнено».

Правила (согласованы с куратором):

* тренировка, совпадающая со слотом недельного расписания (тот же день
  недели и время начала), заканчивается в ``end`` этого слота;
* прочие события со временем (тренировка вне шаблона, игра) — через
  ``DEFAULT_EVENT_DURATION`` после начала;
* событие без времени — в конце дня (00:00 следующих суток).

Время — «настенное» в часовом поясе клуба (naive ``datetime``), как и
``event_date``/``event_time`` в БД.
"""

from datetime import datetime, time, timedelta

from avrora_bot.domain.entities import CalendarEvent, ScheduleSlot
from avrora_bot.domain.enums import EventType

DEFAULT_EVENT_DURATION = timedelta(hours=2)


def event_end(event: CalendarEvent, slots: list[ScheduleSlot]) -> datetime:
    """Возвращает момент окончания события."""
    if event.event_time is None:
        return datetime.combine(event.event_date, time()) + timedelta(days=1)
    start = datetime.combine(event.event_date, event.event_time)
    if event.event_type is EventType.TRAINING:
        weekday = event.event_date.weekday()
        for slot in slots:
            if slot.weekday.index == weekday and slot.start == event.event_time:
                return datetime.combine(event.event_date, slot.end)
    return start + DEFAULT_EVENT_DURATION
