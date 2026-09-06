"""Декларативная база SQLAlchemy для всех ORM-моделей."""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Общий базовый класс ORM-моделей."""


class TimestampMixin:
    """Добавляет столбец ``created_at`` со значением по умолчанию."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
