"""initial schema

Персональные данные пользователя (ФИО, телефон, дата рождения, рост)
изначально вынесены из ``users`` в отдельные таблицы 1:1
(``user_full_names``, ``user_phones``, ``user_birthdates``,
``user_heights``) — см. ``avrora_bot.adapters.database.models``.
ФИО и телефон дополнительно шифруются на уровне приложения
(AES-256-GCM, см. ``avrora_bot.adapters.database.crypto``); миграция
только создаёт колонки под уже зашифрованные байты и сама шифрованием
не занимается.

Revision ID: 3a0b543ec428
Revises:
Create Date: 2026-09-04 16:32:16.049520
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '3a0b543ec428'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'action_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('actor_vk_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=128), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_action_log_actor_vk_id'),
        'action_log',
        ['actor_vk_id'],
        unique=False,
    )
    op.create_table(
        'calendar_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('event_time', sa.Time(), nullable=True),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('place', sa.String(length=256), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('author_vk_id', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_calendar_events_event_date'),
        'calendar_events',
        ['event_date'],
        unique=False,
    )
    op.create_table(
        'schedule_template',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('weekday', sa.String(length=32), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('period_year', sa.Integer(), nullable=False),
        sa.Column('period_month', sa.Integer(), nullable=False),
        sa.Column(
            'total_amount', sa.Numeric(precision=12, scale=2), nullable=False
        ),
        sa.Column('voters_count', sa.Integer(), nullable=False),
        sa.Column(
            'per_person_amount',
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'period_year', 'period_month', name='uq_subscription_period'
        ),
    )
    op.create_table(
        'tariffs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('valid_from', sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tariffs_kind'), 'tariffs', ['kind'], unique=False)
    op.create_index(
        op.f('ix_tariffs_valid_from'), 'tariffs', ['valid_from'], unique=False
    )
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vk_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_vk_id'), 'users', ['vk_id'], unique=True)
    op.create_table(
        'user_full_names',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('full_name_enc', sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_table(
        'user_phones',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('phone_enc', sa.LargeBinary(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_table(
        'user_birthdates',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('birthdate', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_table(
        'user_heights',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('height_cm', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_table(
        'one_time_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('visit_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('marked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('marked_by_vk_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_one_time_payments_user_id'),
        'one_time_payments',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_one_time_payments_visit_date'),
        'one_time_payments',
        ['visit_date'],
        unique=False,
    )
    op.create_table(
        'subscription_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('marked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('marked_by_vk_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['subscription_id'], ['subscriptions.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'subscription_id', 'user_id', name='uq_subscription_payment'
        ),
    )
    op.create_index(
        op.f('ix_subscription_payments_subscription_id'),
        'subscription_payments',
        ['subscription_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_subscription_payments_user_id'),
        'subscription_payments',
        ['user_id'],
        unique=False,
    )
    op.create_table(
        'user_roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column(
            'assigned_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'role', name='uq_user_role'),
    )
    op.create_index(
        op.f('ix_user_roles_user_id'), 'user_roles', ['user_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_user_roles_user_id'), table_name='user_roles')
    op.drop_table('user_roles')
    op.drop_index(
        op.f('ix_subscription_payments_user_id'),
        table_name='subscription_payments',
    )
    op.drop_index(
        op.f('ix_subscription_payments_subscription_id'),
        table_name='subscription_payments',
    )
    op.drop_table('subscription_payments')
    op.drop_index(
        op.f('ix_one_time_payments_visit_date'), table_name='one_time_payments'
    )
    op.drop_index(
        op.f('ix_one_time_payments_user_id'), table_name='one_time_payments'
    )
    op.drop_table('one_time_payments')
    op.drop_table('user_heights')
    op.drop_table('user_birthdates')
    op.drop_table('user_phones')
    op.drop_table('user_full_names')
    op.drop_index(op.f('ix_users_vk_id'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_tariffs_valid_from'), table_name='tariffs')
    op.drop_index(op.f('ix_tariffs_kind'), table_name='tariffs')
    op.drop_table('tariffs')
    op.drop_table('subscriptions')
    op.drop_table('schedule_template')
    op.drop_index(
        op.f('ix_calendar_events_event_date'), table_name='calendar_events'
    )
    op.drop_table('calendar_events')
    op.drop_index(op.f('ix_action_log_actor_vk_id'), table_name='action_log')
    op.drop_table('action_log')
