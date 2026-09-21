"""one time payment note

Добавляет ``one_time_payments.note`` — свободное примечание сборщика к
разовому посещению (кто именно заплатил за гостя, ссылка на ВК и т. п.).
Поле заполняется вручную через «редактировать оплату <id>» и выводится
колонкой «Примечание» в XLSX-отчёте по разовым посещениям (ТЗ 3.2 п.4).

Revision ID: 7c4e1b02af35
Revises: 50556f5ff295
Create Date: 2026-09-21 12:10:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '7c4e1b02af35'
down_revision: str | None = '50556f5ff295'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'one_time_payments',
        sa.Column('note', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('one_time_payments', 'note')
