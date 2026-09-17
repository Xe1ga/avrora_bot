"""nullable user vk_id

Разрешает ``users.vk_id = NULL`` — для игроков, добавленных вручную без
аккаунта ВК (RegistrationUseCases.admin_add_player_without_vk). Учёт по
ним (абонементы, разовые посещения) ведётся так же, как по остальным:
приложение находит их по ФИО (``user_lookup.resolve_user``), а не по
vk_id. Существующий UNIQUE-индекс на ``vk_id`` не требует изменений —
и SQLite, и Postgres в проде считают несколько NULL различными значениями
под обычным UNIQUE.

Revision ID: 1924c9a68584
Revises: 156e6e98e886
Create Date: 2026-09-17 14:30:10.606379
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '1924c9a68584'
down_revision: str | None = '156e6e98e886'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table — SQLite (тесты) не поддерживает ALTER COLUMN и
    # требует пересборки таблицы; на Postgres (прод) тот же код даёт
    # обычный ALTER TABLE ... ALTER COLUMN.
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column(
            'vk_id', existing_type=sa.Integer(), nullable=True
        )


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column(
            'vk_id', existing_type=sa.Integer(), nullable=False
        )
