"""split user pii into separate tables

Выносит ФИО, телефон, дату рождения и рост из ``users`` в четыре отдельные
таблицы 1:1 (``user_full_names``, ``user_phones``, ``user_birthdates``,
``user_heights``). ФИО и телефон дополнительно шифруются на уровне
приложения (AES-256-GCM, см. ``avrora_bot.adapters.database.crypto``) —
в БД остаются только зашифрованные байты.

В БД уже могут быть реальные пользователи, поэтому миграция переносит
существующие данные, а не просто пересоздаёт схему: читает текущие
значения из ``users``, шифрует ФИО/телефон и вставляет их в новые
таблицы, и только после этого удаляет старые колонки. ``downgrade``
выполняет обратное действие (расшифровывает и восстанавливает колонки).

Ключ шифрования берётся из настроек приложения (``PII_ENCRYPTION_KEY``) —
он обязан быть задан в окружении/``.env`` уже на момент запуска
``alembic upgrade``/``downgrade``, аналогично ``POSTGRES_PASSWORD``.

Revision ID: e76a3594ca1f
Revises: 3a0b543ec428
Create Date: 2026-09-11 15:21:52.152781
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from avrora_bot.adapters.database.crypto import PiiCipher, decode_pii_key
from avrora_bot.config import get_settings


revision: str = 'e76a3594ca1f'
down_revision: str | None = '3a0b543ec428'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cipher() -> PiiCipher:
    """Собирает ``PiiCipher`` из ключа в настройках приложения."""
    settings = get_settings()
    key = decode_pii_key(settings.pii_encryption_key.get_secret_value())
    return PiiCipher(key)


def upgrade() -> None:
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

    bind = op.get_bind()
    cipher = _cipher()

    users_table = sa.table(
        'users',
        sa.column('id', sa.Integer),
        sa.column('full_name', sa.String),
        sa.column('phone', sa.String),
        sa.column('birthdate', sa.Date),
        sa.column('height_cm', sa.Integer),
    )
    rows = bind.execute(
        sa.select(
            users_table.c.id,
            users_table.c.full_name,
            users_table.c.phone,
            users_table.c.birthdate,
            users_table.c.height_cm,
        )
    ).fetchall()

    full_name_rows = []
    phone_rows = []
    birthdate_rows = []
    height_rows = []
    for row in rows:
        full_name_rows.append(
            {
                'user_id': row.id,
                'full_name_enc': cipher.encrypt_str(row.full_name),
            }
        )
        phone_rows.append(
            {'user_id': row.id, 'phone_enc': cipher.encrypt_opt(row.phone)}
        )
        birthdate_rows.append({'user_id': row.id, 'birthdate': row.birthdate})
        height_rows.append({'user_id': row.id, 'height_cm': row.height_cm})

    if full_name_rows:
        bind.execute(
            sa.table(
                'user_full_names',
                sa.column('user_id', sa.Integer),
                sa.column('full_name_enc', sa.LargeBinary),
            ).insert(),
            full_name_rows,
        )
    if phone_rows:
        bind.execute(
            sa.table(
                'user_phones',
                sa.column('user_id', sa.Integer),
                sa.column('phone_enc', sa.LargeBinary),
            ).insert(),
            phone_rows,
        )
    if birthdate_rows:
        bind.execute(
            sa.table(
                'user_birthdates',
                sa.column('user_id', sa.Integer),
                sa.column('birthdate', sa.Date),
            ).insert(),
            birthdate_rows,
        )
    if height_rows:
        bind.execute(
            sa.table(
                'user_heights',
                sa.column('user_id', sa.Integer),
                sa.column('height_cm', sa.Integer),
            ).insert(),
            height_rows,
        )

    op.drop_column('users', 'full_name')
    op.drop_column('users', 'phone')
    op.drop_column('users', 'birthdate')
    op.drop_column('users', 'height_cm')


def downgrade() -> None:
    op.add_column(
        'users', sa.Column('full_name', sa.String(length=256), nullable=True)
    )
    op.add_column(
        'users', sa.Column('phone', sa.String(length=32), nullable=True)
    )
    op.add_column('users', sa.Column('birthdate', sa.Date(), nullable=True))
    op.add_column('users', sa.Column('height_cm', sa.Integer(), nullable=True))

    bind = op.get_bind()
    cipher = _cipher()

    full_names = bind.execute(
        sa.text('SELECT user_id, full_name_enc FROM user_full_names')
    ).fetchall()
    for user_id, blob in full_names:
        bind.execute(
            sa.text('UPDATE users SET full_name = :fn WHERE id = :uid'),
            {'fn': cipher.decrypt_str(blob), 'uid': user_id},
        )

    phones = bind.execute(
        sa.text('SELECT user_id, phone_enc FROM user_phones')
    ).fetchall()
    for user_id, blob in phones:
        bind.execute(
            sa.text('UPDATE users SET phone = :p WHERE id = :uid'),
            {'p': cipher.decrypt_opt(blob), 'uid': user_id},
        )

    birthdates = bind.execute(
        sa.text('SELECT user_id, birthdate FROM user_birthdates')
    ).fetchall()
    for user_id, bd in birthdates:
        bind.execute(
            sa.text('UPDATE users SET birthdate = :bd WHERE id = :uid'),
            {'bd': bd, 'uid': user_id},
        )

    heights = bind.execute(
        sa.text('SELECT user_id, height_cm FROM user_heights')
    ).fetchall()
    for user_id, h in heights:
        bind.execute(
            sa.text('UPDATE users SET height_cm = :h WHERE id = :uid'),
            {'h': h, 'uid': user_id},
        )

    # SQLite не поддерживает ALTER COLUMN ... SET NOT NULL напрямую —
    # batch_alter_table пересоздаёт таблицу под капотом на SQLite и
    # выполняет обычный ALTER COLUMN на остальных диалектах (Postgres).
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('full_name', nullable=False)

    op.drop_table('user_heights')
    op.drop_table('user_birthdates')
    op.drop_table('user_phones')
    op.drop_table('user_full_names')
