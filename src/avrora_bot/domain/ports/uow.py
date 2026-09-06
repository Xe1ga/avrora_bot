"""Порт Unit of Work — атомарная граница транзакции.

Слой приложения работает с ``UnitOfWork`` как с async-контекстным менеджером:
внутри него доступны все репозитории, а по выходу транзакция фиксируется
(``commit``) либо откатывается при исключении.
"""

from types import TracebackType
from typing import Protocol

from avrora_bot.domain.ports.repositories import (
    ActionLogRepository,
    CalendarRepository,
    OneTimeRepository,
    RoleRepository,
    ScheduleRepository,
    SubscriptionRepository,
    TariffRepository,
    UserRepository,
)


class UnitOfWork(Protocol):
    """Единица работы: набор репозиториев + управление транзакцией."""

    users: UserRepository
    roles: RoleRepository
    tariffs: TariffRepository
    schedule: ScheduleRepository
    subscriptions: SubscriptionRepository
    one_time: OneTimeRepository
    calendar: CalendarRepository
    action_log: ActionLogRepository

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
