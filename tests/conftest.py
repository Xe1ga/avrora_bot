"""Общие фикстуры тестов."""

from collections.abc import AsyncIterator, Callable

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from avrora_bot.adapters.database.base import Base
from avrora_bot.adapters.database.engine import create_session_factory
from avrora_bot.adapters.database.unit_of_work import SqlAlchemyUnitOfWork
from avrora_bot.domain.ports.uow import UnitOfWork


class FakeVkGateway:
    """Подставной шлюз VK для тестов (без сети)."""

    def __init__(self, admins: set[int] | None = None) -> None:
        self.admins = admins or set()
        self.sent: list[tuple[int, str]] = []

    async def is_group_admin(self, vk_id: int) -> bool:
        return vk_id in self.admins

    async def send_message(self, peer_id: int, text: str) -> None:
        self.sent.append((peer_id, text))

    async def send_document(
        self, peer_id: int, file_path: str, message: str = ''
    ) -> None:
        self.sent.append((peer_id, file_path))


@pytest_asyncio.fixture
async def uow_factory() -> AsyncIterator[Callable[[], UnitOfWork]]:
    """Фабрика Unit of Work поверх in-memory SQLite."""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = create_session_factory(engine)

    def factory() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    yield factory
    await engine.dispose()
