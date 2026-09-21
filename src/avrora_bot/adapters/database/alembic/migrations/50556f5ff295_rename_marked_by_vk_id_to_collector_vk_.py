"""rename marked_by_vk_id to collector_vk_id

Переименовывает ``subscription_payments.marked_by_vk_id`` и
``one_time_payments.marked_by_vk_id`` в ``collector_vk_id`` — по сути это
vk_id сборщика, который фактически собрал оплату, а не просто «кто
поставил отметку» (см. OneTimeUseCases.set_visit_collector).

Revision ID: 50556f5ff295
Revises: 1924c9a68584
Create Date: 2026-09-17 15:30:45.732960
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '50556f5ff295'
down_revision: str | None = '1924c9a68584'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('subscription_payments') as batch_op:
        batch_op.alter_column(
            'marked_by_vk_id',
            new_column_name='collector_vk_id',
            existing_type=sa.Integer(),
        )
    with op.batch_alter_table('one_time_payments') as batch_op:
        batch_op.alter_column(
            'marked_by_vk_id',
            new_column_name='collector_vk_id',
            existing_type=sa.Integer(),
        )


def downgrade() -> None:
    with op.batch_alter_table('subscription_payments') as batch_op:
        batch_op.alter_column(
            'collector_vk_id',
            new_column_name='marked_by_vk_id',
            existing_type=sa.Integer(),
        )
    with op.batch_alter_table('one_time_payments') as batch_op:
        batch_op.alter_column(
            'collector_vk_id',
            new_column_name='marked_by_vk_id',
            existing_type=sa.Integer(),
        )
