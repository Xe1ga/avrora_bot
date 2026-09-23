"""schedule template place

Добавляет ``schedule_template.place`` — место/тренер по умолчанию для слота
недельного расписания. «Создать тренировки на следующий месяц» подставляет
его в ``calendar_events.place`` создаваемых тренировок.

Значения заполняются по анализу тренировок сентября 2026 и решению куратора:
Вт 19:00 и Пт 19:00 — Волкова, Вт 20:30 и Чт 19:30 — Крылов. Слоты ищутся
по (weekday, start_time); если такого слота нет, UPDATE его просто не
затронет.

Revision ID: d6701f18890b
Revises: 7c4e1b02af35
Create Date: 2026-09-23 22:30:00.000000
"""
from collections.abc import Sequence
from datetime import time

from alembic import op
import sqlalchemy as sa


revision: str = 'd6701f18890b'
down_revision: str | None = '7c4e1b02af35'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PLACE_VOLKOVA = '15 школа, тренер Волкова Елена'
_PLACE_KRYLOV = '15 школа, тренер Крылов Дмитрий'

_DEFAULT_PLACES: tuple[tuple[str, time, str], ...] = (
    ('tuesday', time(19, 0), _PLACE_VOLKOVA),
    ('tuesday', time(20, 30), _PLACE_KRYLOV),
    ('thursday', time(19, 30), _PLACE_KRYLOV),
    ('friday', time(19, 0), _PLACE_VOLKOVA),
)


def upgrade() -> None:
    op.add_column(
        'schedule_template',
        sa.Column('place', sa.String(length=256), nullable=True),
    )

    schedule_template = sa.table(
        'schedule_template',
        sa.column('weekday', sa.String),
        sa.column('start_time', sa.Time),
        sa.column('place', sa.String),
    )
    for weekday, start_time, place in _DEFAULT_PLACES:
        op.execute(
            schedule_template.update()
            .where(
                schedule_template.c.weekday == weekday,
                schedule_template.c.start_time == start_time,
            )
            .values(place=place)
        )


def downgrade() -> None:
    op.drop_column('schedule_template', 'place')
