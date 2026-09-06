"""Асинхронный движок и фабрика сессий SQLAlchemy."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(dsn: str, *, echo: bool = False) -> AsyncEngine:
    """Создаёт асинхронный движок для указанного DSN (asyncpg)."""
    return create_async_engine(dsn, echo=echo, pool_pre_ping=True)


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Создаёт фабрику сессий.

    ``expire_on_commit=False`` — объекты остаются доступными после commit,
    что удобно для передачи данных за пределы Unit of Work.
    """
    return async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
