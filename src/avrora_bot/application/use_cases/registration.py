"""Use case'ы регистрации пользователей (ТЗ 3.6)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.domain.entities import User
from avrora_bot.domain.enums import RoleName, UserStatus
from avrora_bot.domain.errors import AlreadyExistsError, NotFoundError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway

UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class RegistrationData:
    """Данные заявки на регистрацию."""

    vk_id: int
    full_name: str
    birthdate: date | None = None
    height_cm: int | None = None
    phone: str | None = None


class RegistrationUseCases:
    """Самостоятельная регистрация и её подтверждение администратором."""

    def __init__(self, uow_factory: UowFactory, vk_gateway: VkGateway) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway

    async def self_register(self, data: RegistrationData) -> User:
        """Создаёт заявку игрока со статусом ``pending``.

        :raises AlreadyExistsError: если профиль с таким vk_id уже есть.
        """
        async with self._uow_factory() as uow:
            existing = await uow.users.get_by_vk_id(data.vk_id)
            if existing is not None:
                raise AlreadyExistsError(
                    'Профиль уже существует или заявка подана'
                )
            user = await uow.users.add(
                User(
                    vk_id=data.vk_id,
                    full_name=data.full_name,
                    status=UserStatus.PENDING,
                    birthdate=data.birthdate,
                    height_cm=data.height_cm,
                    phone=data.phone,
                )
            )
            await uow.commit()
            return user

    async def get_profile(self, vk_id: int) -> User | None:
        """Возвращает профиль пользователя по vk_id (без проверки прав)."""
        async with self._uow_factory() as uow:
            return await uow.users.get_by_vk_id(vk_id)

    async def admin_add_user(
        self, admin_vk_id: int, data: RegistrationData, role: RoleName
    ) -> User:
        """Ручное добавление пользователя администратором по vk_id (ТЗ 3.6).

        Профиль создаётся со статусом ``pending``, но роль назначается сразу.
        """
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, admin_vk_id)
            existing = await uow.users.get_by_vk_id(data.vk_id)
            if existing is not None:
                raise AlreadyExistsError('Профиль уже существует')
            user = await uow.users.add(
                User(
                    vk_id=data.vk_id,
                    full_name=data.full_name,
                    status=UserStatus.PENDING,
                    birthdate=data.birthdate,
                    height_cm=data.height_cm,
                    phone=data.phone,
                )
            )
            await uow.roles.assign(user.id, role)
            await record_action(
                uow,
                admin_vk_id,
                'user.add',
                f'vk_id={data.vk_id} role={role.value}',
            )
            await uow.commit()
            return user

    async def list_pending(self, admin_vk_id: int) -> list[User]:
        """Возвращает заявки, ожидающие подтверждения."""
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, admin_vk_id)
            return await uow.users.list_by_status(UserStatus.PENDING)

    async def approve(self, admin_vk_id: int, vk_id: int) -> User:
        """Подтверждает заявку: статус ``active`` + роль ``player``."""
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, admin_vk_id)
            user = await uow.users.get_by_vk_id(vk_id)
            if user is None:
                raise NotFoundError('Заявка не найдена')
            user.status = UserStatus.ACTIVE
            await uow.users.update(user)
            await uow.roles.assign(user.id, RoleName.PLAYER)
            await record_action(
                uow, admin_vk_id, 'user.approve', f'vk_id={vk_id}'
            )
            await uow.commit()
            return user

    async def reject(self, admin_vk_id: int, vk_id: int) -> User:
        """Отклоняет заявку (статус ``rejected``)."""
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, admin_vk_id)
            user = await uow.users.get_by_vk_id(vk_id)
            if user is None:
                raise NotFoundError('Заявка не найдена')
            user.status = UserStatus.REJECTED
            await uow.users.update(user)
            await record_action(
                uow, admin_vk_id, 'user.reject', f'vk_id={vk_id}'
            )
            await uow.commit()
            return user
