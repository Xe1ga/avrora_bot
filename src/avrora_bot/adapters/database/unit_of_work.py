"""Реализация Unit of Work поверх ``AsyncSession``."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from avrora_bot.adapters.database.crypto import PiiCipher
from avrora_bot.adapters.database.repositories import (
    SqlActionLogRepository,
    SqlCalendarRepository,
    SqlConsentRepository,
    SqlLegalDocumentRepository,
    SqlOneTimeRepository,
    SqlRoleRepository,
    SqlScheduleRepository,
    SqlSubscriptionRepository,
    SqlTariffRepository,
    SqlUserRepository,
)


class SqlAlchemyUnitOfWork:
    """Открывает сессию и предоставляет репозитории в рамках транзакции.

    Использование::

        async with uow_factory() as uow:
            user = await uow.users.get_by_vk_id(123)
            await uow.commit()
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cipher: PiiCipher,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        s = self._session
        self.users = SqlUserRepository(s, self._cipher)
        self.roles = SqlRoleRepository(s, self._cipher)
        self.tariffs = SqlTariffRepository(s)
        self.schedule = SqlScheduleRepository(s)
        self.subscriptions = SqlSubscriptionRepository(s)
        self.one_time = SqlOneTimeRepository(s)
        self.calendar = SqlCalendarRepository(s)
        self.action_log = SqlActionLogRepository(s)
        self.legal_documents = SqlLegalDocumentRepository(s)
        self.consents = SqlConsentRepository(s)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            if exc_type is not None:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()
