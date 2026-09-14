"""user consents

Журнал согласий на обработку персональных данных (ТЗ 3.6, 152-ФЗ):
append-only таблица — одна строка на каждый факт согласия. Если текст
согласия впоследствии изменится и потребуется повторное согласие
пользователя, новая строка добавляется, а старые сохраняются как история
(кто, когда и с какой версией документа согласился).

Revision ID: dbfcf9cc49c3
Revises: 3a0b543ec428
Create Date: 2026-09-14 16:40:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'dbfcf9cc49c3'
down_revision: str | None = '3a0b543ec428'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'user_consents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=False),
        sa.Column(
            'given_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_user_consents_user_id'),
        'user_consents',
        ['user_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_user_consents_user_id'), table_name='user_consents'
    )
    op.drop_table('user_consents')
