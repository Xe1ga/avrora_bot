"""Use case'ы управления ролями (ТЗ 2)."""

from collections.abc import Callable

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.domain.entities import User
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import NotFoundError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway

UowFactory = Callable[[], UnitOfWork]


class RoleUseCases:
    """Назначение и отзыв ролей администратором."""

    def __init__(self, uow_factory: UowFactory, vk_gateway: VkGateway) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway

    async def assign_role(
        self, admin_vk_id: int, target_vk_id: int, role: RoleName
    ) -> None:
        """Назначает роль пользователю (только администратор)."""
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, admin_vk_id)
            user = await uow.users.get_by_vk_id(target_vk_id)
            if user is None:
                raise NotFoundError('Пользователь не найден')
            await uow.roles.assign(user.id, role)
            await record_action(
                uow,
                admin_vk_id,
                'role.assign',
                f'vk_id={target_vk_id} role={role.value}',
            )
            await uow.commit()

    async def revoke_role(
        self, admin_vk_id: int, target_vk_id: int, role: RoleName
    ) -> None:
        """Отзывает роль у пользователя (только администратор)."""
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, admin_vk_id)
            user = await uow.users.get_by_vk_id(target_vk_id)
            if user is None:
                raise NotFoundError('Пользователь не найден')
            await uow.roles.revoke(user.id, role)
            await record_action(
                uow,
                admin_vk_id,
                'role.revoke',
                f'vk_id={target_vk_id} role={role.value}',
            )
            await uow.commit()

    async def list_by_role(
        self, admin_vk_id: int, role: RoleName
    ) -> list[User]:
        """Список пользователей с заданной ролью."""
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, admin_vk_id)
            return await uow.roles.users_with_role(role)
