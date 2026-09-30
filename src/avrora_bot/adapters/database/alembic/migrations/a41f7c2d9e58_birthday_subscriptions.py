"""birthday subscriptions

Напоминания о днях рождения для роли «Поздравитель» (``greeter``).

Новые таблицы:

* ``birthday_subscriptions`` — кто из поздравителей за чьим днём рождения
  следит (у каждого свой список);
* ``birthday_reminders`` — журнал отправленных напоминаний: вид
  (``ten_days`` — заранее, ``on_day`` — в день рождения, ``next_month`` —
  сводка в последний день месяца) и ``occasion`` — дата дня рождения, о
  котором напомнили. Уникальность не даёт отправить одно и то же дважды.

Сама роль хранится строкой в ``user_roles.role`` — изменений схемы для неё
не требуется.

Revision ID: a41f7c2d9e58
Revises: d9ac753eb726
Create Date: 2026-09-30 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a41f7c2d9e58'
down_revision: str | None = 'd9ac753eb726'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'birthday_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('subscriber_user_id', sa.Integer(), nullable=False),
        sa.Column('target_user_id', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['subscriber_user_id'], ['users.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['target_user_id'], ['users.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'subscriber_user_id',
            'target_user_id',
            name='uq_birthday_subscription',
        ),
    )
    op.create_index(
        op.f('ix_birthday_subscriptions_subscriber_user_id'),
        'birthday_subscriptions',
        ['subscriber_user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_birthday_subscriptions_target_user_id'),
        'birthday_subscriptions',
        ['target_user_id'],
        unique=False,
    )

    op.create_table(
        'birthday_reminders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('subscriber_user_id', sa.Integer(), nullable=False),
        sa.Column('target_user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('occasion', sa.Date(), nullable=False),
        sa.Column(
            'sent_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['subscriber_user_id'], ['users.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['target_user_id'], ['users.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'subscriber_user_id',
            'target_user_id',
            'kind',
            'occasion',
            name='uq_birthday_reminder',
        ),
    )
    op.create_index(
        op.f('ix_birthday_reminders_subscriber_user_id'),
        'birthday_reminders',
        ['subscriber_user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_birthday_reminders_target_user_id'),
        'birthday_reminders',
        ['target_user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_birthday_reminders_occasion'),
        'birthday_reminders',
        ['occasion'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_birthday_reminders_occasion'), table_name='birthday_reminders'
    )
    op.drop_index(
        op.f('ix_birthday_reminders_target_user_id'),
        table_name='birthday_reminders',
    )
    op.drop_index(
        op.f('ix_birthday_reminders_subscriber_user_id'),
        table_name='birthday_reminders',
    )
    op.drop_table('birthday_reminders')
    op.drop_index(
        op.f('ix_birthday_subscriptions_target_user_id'),
        table_name='birthday_subscriptions',
    )
    op.drop_index(
        op.f('ix_birthday_subscriptions_subscriber_user_id'),
        table_name='birthday_subscriptions',
    )
    op.drop_table('birthday_subscriptions')
