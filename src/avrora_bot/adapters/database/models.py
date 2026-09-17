"""ORM-модели SQLAlchemy (соответствуют разделу 4.3 ТЗ).

Денежные значения — ``Numeric(12, 2)`` (Decimal), даты событий — ``Date``,
временные метки — ``DateTime(timezone=True)``.

Заложено на будущее (создаются пустыми на Этапе 1, наполняются позже):
    posts_log        — журнал постов (Этап 2)
    gift_collections — сборы на подарки (Этап 3)
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from avrora_bot.adapters.database.base import Base, TimestampMixin
from avrora_bot.domain.enums import (
    EventType,
    LegalDocumentKind,
    PaymentStatus,
    RoleName,
    TariffKind,
    UserStatus,
    Weekday,
)

# Длины строковых полей.
_PLACE_LEN = 256
_ACTION_LEN = 128
_ENUM_LEN = 32
_DOC_VERSION_LEN = 32
_URL_LEN = 512
_SHA256_LEN = 64


class UserRole(Base):
    """Связь пользователь ↔ роль (many-to-many) с датой назначения."""

    __tablename__ = 'user_roles'
    __table_args__ = (UniqueConstraint('user_id', 'role', name='uq_user_role'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    role: Mapped[RoleName] = mapped_column(String(_ENUM_LEN))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates='role_links')


class User(Base, TimestampMixin):
    """Пользователь клуба.

    Персональные данные (ФИО, телефон, дата рождения, рост) вынесены в
    отдельные таблицы 1:1 (см. ``UserFullName``, ``UserPhone``,
    ``UserBirthdate``, ``UserHeight``) — ФИО и телефон дополнительно
    шифруются на уровне приложения (``adapters/database/crypto.py``).
    """

    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL — игрок, добавленный вручную без аккаунта ВК (RegistrationUseCases.
    # admin_add_player_without_vk); обычный UNIQUE-индекс здесь не мешает
    # заводить сколько угодно таких записей — NULL в SQL всегда «не равен»
    # другому NULL, так что уникальность проверяется только для заданных
    # значений (это верно и для SQLite, и для Postgres в проде).
    vk_id: Mapped[int | None] = mapped_column(
        Integer, unique=True, index=True, nullable=True
    )
    status: Mapped[UserStatus] = mapped_column(
        String(_ENUM_LEN), default=UserStatus.PENDING
    )

    role_links: Mapped[list[UserRole]] = relationship(
        back_populates='user', cascade='all, delete-orphan'
    )
    full_name_link: Mapped[UserFullName | None] = relationship(
        back_populates='user', cascade='all, delete-orphan', uselist=False
    )
    phone_link: Mapped[UserPhone | None] = relationship(
        back_populates='user', cascade='all, delete-orphan', uselist=False
    )
    birthdate_link: Mapped[UserBirthdate | None] = relationship(
        back_populates='user', cascade='all, delete-orphan', uselist=False
    )
    height_link: Mapped[UserHeight | None] = relationship(
        back_populates='user', cascade='all, delete-orphan', uselist=False
    )


class UserFullName(Base):
    """ФИО пользователя, хранится в зашифрованном виде (AES-256-GCM)."""

    __tablename__ = 'user_full_names'

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), primary_key=True
    )
    full_name_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    user: Mapped[User] = relationship(back_populates='full_name_link')


class UserPhone(Base):
    """Телефон пользователя, хранится в зашифрованном виде (AES-256-GCM)."""

    __tablename__ = 'user_phones'

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), primary_key=True
    )
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    user: Mapped[User] = relationship(back_populates='phone_link')


class UserBirthdate(Base):
    """Дата рождения пользователя (без шифрования)."""

    __tablename__ = 'user_birthdates'

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), primary_key=True
    )
    birthdate: Mapped[date | None] = mapped_column(Date, nullable=True)

    user: Mapped[User] = relationship(back_populates='birthdate_link')


class UserHeight(Base):
    """Рост пользователя, см (без шифрования)."""

    __tablename__ = 'user_heights'

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), primary_key=True
    )
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User] = relationship(back_populates='height_link')


class LegalDocument(Base, TimestampMixin):
    """Версия юридического документа из ``docs/legal/`` (ТЗ 3.6, 152-ФЗ).

    Append-only справочник версий: одна строка — один опубликованный текст
    (``consent.html`` или ``privacy-policy.html``) с версией и датой из
    заголовка страницы, ссылкой на публикацию, sha256 файла и полным HTML
    на момент фиксации. Строки не обновляются и не удаляются: на них
    ссылается журнал согласий (``UserConsent``), поэтому текст, с которым
    согласился пользователь, всегда восстановим из БД, даже если файл в
    репозитории потом переписали.

    Новые версии регистрируются автоматически при старте приложения
    (``adapters.database.seed.sync_legal_documents``) по файлам из
    ``docs/legal/``.
    """

    __tablename__ = 'legal_documents'
    __table_args__ = (
        UniqueConstraint('kind', 'version', name='uq_legal_document_version'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[LegalDocumentKind] = mapped_column(
        String(_ENUM_LEN), index=True
    )
    version: Mapped[str] = mapped_column(String(_DOC_VERSION_LEN))
    # Дата вступления в силу из заголовка «Версия X.Y от ДД месяца ГГГГ г.».
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Адрес публикации на момент регистрации версии (GitHub Pages и т. п.).
    url: Mapped[str | None] = mapped_column(String(_URL_LEN), nullable=True)
    sha256: Mapped[str] = mapped_column(String(_SHA256_LEN))
    content: Mapped[str] = mapped_column(Text)

    consents_as_consent: Mapped[list[UserConsent]] = relationship(
        back_populates='consent_document',
        foreign_keys='UserConsent.consent_document_id',
    )
    consents_as_privacy_policy: Mapped[list[UserConsent]] = relationship(
        back_populates='privacy_policy_document',
        foreign_keys='UserConsent.privacy_policy_document_id',
    )


class UserConsent(Base):
    """Факт согласия на обработку персональных данных (ТЗ 3.6, 152-ФЗ).

    Append-only: строки не обновляются и не удаляются — это журнал, а не
    текущее состояние. Фиксируются ссылки на конкретные версии обоих
    документов (``legal_documents``), с которыми пользователь ознакомился:
    согласие на обработку ПД и политика обработки ПД. Если текст меняется и
    требуется повторное согласие, добавляется новая строка со ссылками на
    новые версии, старые остаются как история (кто, когда, с чем согласился).
    """

    __tablename__ = 'user_consents'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    consent_document_id: Mapped[int] = mapped_column(
        ForeignKey('legal_documents.id', ondelete='RESTRICT'), index=True
    )
    privacy_policy_document_id: Mapped[int] = mapped_column(
        ForeignKey('legal_documents.id', ondelete='RESTRICT'), index=True
    )
    given_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    consent_document: Mapped[LegalDocument] = relationship(
        back_populates='consents_as_consent',
        foreign_keys=[consent_document_id],
    )
    privacy_policy_document: Mapped[LegalDocument] = relationship(
        back_populates='consents_as_privacy_policy',
        foreign_keys=[privacy_policy_document_id],
    )


class Tariff(Base):
    """Тариф с датой начала действия (ведётся история изменений)."""

    __tablename__ = 'tariffs'

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[TariffKind] = mapped_column(String(_ENUM_LEN), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    valid_from: Mapped[date] = mapped_column(Date, index=True)


class ScheduleTemplate(Base):
    """Слот недельного шаблона расписания тренировок."""

    __tablename__ = 'schedule_template'

    id: Mapped[int] = mapped_column(primary_key=True)
    weekday: Mapped[Weekday] = mapped_column(String(_ENUM_LEN))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Subscription(Base, TimestampMixin):
    """Подписка (абонемент) на конкретный месяц."""

    __tablename__ = 'subscriptions'
    __table_args__ = (
        UniqueConstraint(
            'period_year', 'period_month', name='uq_subscription_period'
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    period_year: Mapped[int] = mapped_column(Integer)
    period_month: Mapped[int] = mapped_column(Integer)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    voters_count: Mapped[int] = mapped_column(Integer)
    per_person_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Реальная сумма, зафиксированная сборщиком (ТЗ 3.2) — то, что по факту
    # собирается с участников; используется во всех отчётах по сдаче
    # средств вместо расчётной per_person_amount, когда задана.
    per_percent_amount_fact: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    payments: Mapped[list[SubscriptionPayment]] = relationship(
        back_populates='subscription', cascade='all, delete-orphan'
    )


class SubscriptionPayment(Base):
    """Строка оплаты абонемента для участника."""

    __tablename__ = 'subscription_payments'
    __table_args__ = (
        UniqueConstraint(
            'subscription_id', 'user_id', name='uq_subscription_payment'
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey('subscriptions.id', ondelete='CASCADE'), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    status: Mapped[PaymentStatus] = mapped_column(
        String(_ENUM_LEN), default=PaymentStatus.UNPAID
    )
    marked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    marked_by_vk_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    subscription: Mapped[Subscription] = relationship(back_populates='payments')


class OneTimePayment(Base):
    """Разовое посещение."""

    __tablename__ = 'one_time_payments'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    visit_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[PaymentStatus] = mapped_column(
        String(_ENUM_LEN), default=PaymentStatus.UNPAID
    )
    marked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    marked_by_vk_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CalendarEvent(Base):
    """Событие календаря (тренировка/игра)."""

    __tablename__ = 'calendar_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    event_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    event_type: Mapped[EventType] = mapped_column(String(_ENUM_LEN))
    place: Mapped[str | None] = mapped_column(String(_PLACE_LEN), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_vk_id: Mapped[int] = mapped_column(Integer)


class ActionLog(Base, TimestampMixin):
    """Журнал административных действий (ТЗ 5.5)."""

    __tablename__ = 'action_log'

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_vk_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(_ACTION_LEN))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
