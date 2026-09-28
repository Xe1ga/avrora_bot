"""finance accounting

Финансовый учёт: сколько клубных денег и у кого на руках на любую дату.

Новые таблицы:

* ``expenses`` — расходы (зал, тренер, прочее) с конкретного «счёта» —
  человека, с чьих денег оплачено;
* ``account_transfers`` — передача денег от одного человека другому;
* ``balance_adjustments`` — ручные корректировки остатка администратором
  (начальный остаток на дату запуска учёта, исправление расхождений).

В ``subscription_payments`` добавлены ``amount`` (фактически внесённая
сумма, если отличается от суммы абонемента; NULL — ровно сумма
абонемента) и ``note`` (примечание сборщика, колонка отчёта). Для уже
существующих строк NULL означает прежнее поведение, заполнять нечего.

FK на ``users`` — RESTRICT: финансовая история не удаляется вместе с
пользователем.

Revision ID: d9ac753eb726
Revises: 6248ea5956e7
Create Date: 2026-09-28 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'd9ac753eb726'
down_revision: str | None = '6248ea5956e7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'subscription_payments',
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        'subscription_payments',
        sa.Column('note', sa.Text(), nullable=True),
    )

    op.create_table(
        'expenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('spent_on', sa.Date(), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('description', sa.String(length=256), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('account_user_id', sa.Integer(), nullable=False),
        sa.Column('created_by_vk_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.CheckConstraint('amount > 0', name='ck_expenses_amount_positive'),
        sa.ForeignKeyConstraint(
            ['account_user_id'], ['users.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_expenses_spent_on'), 'expenses', ['spent_on'], unique=False
    )
    op.create_index(
        op.f('ix_expenses_account_user_id'),
        'expenses',
        ['account_user_id'],
        unique=False,
    )

    op.create_table(
        'account_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('transferred_on', sa.Date(), nullable=False),
        sa.Column('from_user_id', sa.Integer(), nullable=False),
        sa.Column('to_user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('created_by_vk_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.CheckConstraint(
            'amount > 0', name='ck_account_transfers_amount_positive'
        ),
        sa.CheckConstraint(
            'from_user_id <> to_user_id',
            name='ck_account_transfers_distinct_users',
        ),
        sa.ForeignKeyConstraint(
            ['from_user_id'], ['users.id'], ondelete='RESTRICT'
        ),
        sa.ForeignKeyConstraint(
            ['to_user_id'], ['users.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_account_transfers_transferred_on'),
        'account_transfers',
        ['transferred_on'],
        unique=False,
    )
    op.create_index(
        op.f('ix_account_transfers_from_user_id'),
        'account_transfers',
        ['from_user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_account_transfers_to_user_id'),
        'account_transfers',
        ['to_user_id'],
        unique=False,
    )

    op.create_table(
        'balance_adjustments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('adjusted_on', sa.Date(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('reason', sa.String(length=256), nullable=False),
        sa.Column('created_by_vk_id', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.CheckConstraint(
            'amount <> 0', name='ck_balance_adjustments_amount_nonzero'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_balance_adjustments_adjusted_on'),
        'balance_adjustments',
        ['adjusted_on'],
        unique=False,
    )
    op.create_index(
        op.f('ix_balance_adjustments_user_id'),
        'balance_adjustments',
        ['user_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_balance_adjustments_user_id'),
        table_name='balance_adjustments',
    )
    op.drop_index(
        op.f('ix_balance_adjustments_adjusted_on'),
        table_name='balance_adjustments',
    )
    op.drop_table('balance_adjustments')

    op.drop_index(
        op.f('ix_account_transfers_to_user_id'),
        table_name='account_transfers',
    )
    op.drop_index(
        op.f('ix_account_transfers_from_user_id'),
        table_name='account_transfers',
    )
    op.drop_index(
        op.f('ix_account_transfers_transferred_on'),
        table_name='account_transfers',
    )
    op.drop_table('account_transfers')

    op.drop_index(op.f('ix_expenses_account_user_id'), table_name='expenses')
    op.drop_index(op.f('ix_expenses_spent_on'), table_name='expenses')
    op.drop_table('expenses')

    op.drop_column('subscription_payments', 'note')
    op.drop_column('subscription_payments', 'amount')
