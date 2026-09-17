"""subscription fact amount

Добавляет ``subscriptions.per_percent_amount_fact`` — реальную фактическую
цену абонемента, зафиксированную сборщиком платежей (ТЗ 3.2). В отличие от
``per_person_amount`` (расчёт по тарифам / число голосов, пересчитывается
при изменении списка проголосовавших), это поле не пересчитывается
автоматически и приоритетно во всех отчётах по сдаче средств.

Revision ID: 156e6e98e886
Revises: dbfcf9cc49c3
Create Date: 2026-09-16 15:47:41.129609
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '156e6e98e886'
down_revision: str | None = 'dbfcf9cc49c3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'subscriptions',
        sa.Column(
            'per_percent_amount_fact',
            sa.Numeric(precision=12, scale=2),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('subscriptions', 'per_percent_amount_fact')
