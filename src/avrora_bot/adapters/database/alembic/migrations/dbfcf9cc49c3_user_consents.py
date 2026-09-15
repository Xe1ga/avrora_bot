"""user consents

Версии юридических документов и журнал согласий на обработку персональных
данных (ТЗ 3.6, 152-ФЗ).

``legal_documents`` — append-only справочник версий документов из
``docs/legal/`` (согласие на обработку ПД и политика обработки ПД): версия и
дата из заголовка страницы, ссылка на публикацию, sha256 файла и полный HTML
на момент регистрации версии. Версии регистрируются приложением при старте
по файлам репозитория.

``user_consents`` — append-only журнал: одна строка на каждый факт согласия,
со ссылками на конкретные версии обоих документов. Если текст изменится и
потребуется повторное согласие, добавляется новая строка, а старые остаются
как история (кто, когда и с каким именно текстом согласился) — поэтому на
``legal_documents`` стоит ``ON DELETE RESTRICT``.

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
        'legal_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=True),
        sa.Column('url', sa.String(length=512), nullable=True),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'kind', 'version', name='uq_legal_document_version'
        ),
    )
    op.create_index(
        op.f('ix_legal_documents_kind'),
        'legal_documents',
        ['kind'],
        unique=False,
    )
    op.create_table(
        'user_consents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('consent_document_id', sa.Integer(), nullable=False),
        sa.Column('privacy_policy_document_id', sa.Integer(), nullable=False),
        sa.Column(
            'given_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['consent_document_id'],
            ['legal_documents.id'],
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['privacy_policy_document_id'],
            ['legal_documents.id'],
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_user_consents_user_id'),
        'user_consents',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_user_consents_consent_document_id'),
        'user_consents',
        ['consent_document_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_user_consents_privacy_policy_document_id'),
        'user_consents',
        ['privacy_policy_document_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_user_consents_privacy_policy_document_id'),
        table_name='user_consents',
    )
    op.drop_index(
        op.f('ix_user_consents_consent_document_id'),
        table_name='user_consents',
    )
    op.drop_index(op.f('ix_user_consents_user_id'), table_name='user_consents')
    op.drop_table('user_consents')
    op.drop_index(op.f('ix_legal_documents_kind'), table_name='legal_documents')
    op.drop_table('legal_documents')
