"""Use case'ы просмотра и редактирования данных пользователя администратором."""

from collections.abc import Callable
from datetime import date

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.domain.entities import User
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import NotFoundError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway

UowFactory = Callable[[], UnitOfWork]
_Mutator = Callable[[User], None]


class UserManagementUseCases:
    """Просмотр профиля и редактирование персональных данных (только админ)."""

    def __init__(self, uow_factory: UowFactory, vk_gateway: VkGateway) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway

    async def effective_roles(self, vk_id: int) -> frozenset[RoleName]:
        """Возвращает роли пользователя (для построения UI, без исключений).

        Включает роль ``admin``, если пользователь — администратор
        сообщества VK, даже без явной роли в БД (см.
        ``permissions.effective_roles``).
        """
        async with self._uow_factory() as uow:
            return await permissions.effective_roles(uow, self._vk, vk_id)

    async def get_user(self, admin_vk_id: int, target_vk_id: int) -> User:
        """Возвращает профиль пользователя для редактирования.

        :raises PermissionDeniedError: если ``admin_vk_id`` не администратор.
        :raises NotFoundError: если пользователь с таким vk_id не найден.
        """
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, admin_vk_id)
            return await self._get_or_raise(uow, target_vk_id)

    async def set_full_name(
        self, admin_vk_id: int, target_vk_id: int, full_name: str
    ) -> User:
        """Меняет ФИО пользователя."""
        return await self._update(
            admin_vk_id,
            target_vk_id,
            'user.edit_full_name',
            lambda user: setattr(user, 'full_name', full_name),
        )

    async def set_phone(
        self, admin_vk_id: int, target_vk_id: int, phone: str | None
    ) -> User:
        """Меняет телефон пользователя (``None`` — очистить)."""
        return await self._update(
            admin_vk_id,
            target_vk_id,
            'user.edit_phone',
            lambda user: setattr(user, 'phone', phone),
        )

    async def set_birthdate(
        self, admin_vk_id: int, target_vk_id: int, birthdate: date | None
    ) -> User:
        """Меняет дату рождения пользователя (``None`` — очистить)."""
        return await self._update(
            admin_vk_id,
            target_vk_id,
            'user.edit_birthdate',
            lambda user: setattr(user, 'birthdate', birthdate),
        )

    async def set_height(
        self, admin_vk_id: int, target_vk_id: int, height_cm: int | None
    ) -> User:
        """Меняет рост пользователя, см (``None`` — очистить)."""
        return await self._update(
            admin_vk_id,
            target_vk_id,
            'user.edit_height',
            lambda user: setattr(user, 'height_cm', height_cm),
        )

    async def _update(
        self,
        admin_vk_id: int,
        target_vk_id: int,
        action: str,
        mutate: _Mutator,
    ) -> User:
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, admin_vk_id)
            user = await self._get_or_raise(uow, target_vk_id)
            mutate(user)
            await uow.users.update(user)
            await record_action(
                uow, admin_vk_id, action, f'vk_id={target_vk_id}'
            )
            await uow.commit()
            return user

    @staticmethod
    async def _get_or_raise(uow: UnitOfWork, target_vk_id: int) -> User:
        user = await uow.users.get_by_vk_id(target_vk_id)
        if user is None:
            raise NotFoundError('Пользователь не найден')
        return user
