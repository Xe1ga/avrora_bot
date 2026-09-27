"""calendar event status

Добавляет ``calendar_events.status``: ``planned`` (запланировано),
``done`` (выполнено), ``cancelled`` (отмена). Новые события получают
``planned``; в ``done`` их переводит фоновая задача бота по истечении
времени события, ``cancelled`` ставит куратор вручную.

Уже прошедшие на момент миграции события (дата раньше сегодняшней)
сразу помечаются ``done``; сегодняшние бот доведёт сам первым же проходом
фоновой задачи при старте.

Revision ID: 6248ea5956e7
Revises: d6701f18890b
Create Date: 2026-09-23 23:30:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '6248ea5956e7'
down_revision: str | None = 'd6701f18890b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'calendar_events',
        sa.Column(
            'status',
            sa.String(length=32),
            nullable=False,
            server_default='planned',
        ),
    )

    calendar_events = sa.table(
        'calendar_events',
        sa.column('event_date', sa.Date),
        sa.column('status', sa.String),
    )
    op.execute(
        calendar_events.update()
        .where(calendar_events.c.event_date < sa.func.current_date())
        .values(status='done')
    )


def downgrade() -> None:
    op.drop_column('calendar_events', 'status')
