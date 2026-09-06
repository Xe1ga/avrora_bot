"""Проверка прав доступа НА МОМЕНТ ВЫПОЛНЕНИЯ (ТЗ 5.2).

Права не кэшируются: роль администратора верифицируется через VK API при
каждом действии, прочие роли читаются из БД в текущей транзакции.
"""

from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import PermissionDeniedError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway


async def is_admin(uow: UnitOfWork, vk_gateway: VkGateway, vk_id: int) -> bool:
    """Проверяет роль администратора.

    Источник истины — VK API (администратор сообщества). Дополнительно
    учитывается явно назначенная в БД роль ``admin`` (bootstrap-администратор,
    который может не быть админом сообщества VK).
    """
    if await vk_gateway.is_group_admin(vk_id):
        return True
    user = await uow.users.get_by_vk_id(vk_id)
    return bool(user and user.has_role(RoleName.ADMIN))


async def has_role(uow: UnitOfWork, vk_id: int, role: RoleName) -> bool:
    """Проверяет наличие конкретной роли у пользователя (по данным БД)."""
    user = await uow.users.get_by_vk_id(vk_id)
    return bool(user and user.has_role(role))


async def require_admin(
    uow: UnitOfWork, vk_gateway: VkGateway, vk_id: int
) -> None:
    """Бросает ``PermissionDeniedError``, если пользователь не администратор."""
    if not await is_admin(uow, vk_gateway, vk_id):
        raise PermissionDeniedError('Требуются права администратора')


async def require_role(
    uow: UnitOfWork,
    vk_gateway: VkGateway,
    vk_id: int,
    role: RoleName,
) -> None:
    """Проверяет наличие роли; администратор имеет доступ ко всему.

    :raises PermissionDeniedError: если прав недостаточно.
    """
    if await is_admin(uow, vk_gateway, vk_id):
        return
    if await has_role(uow, vk_id, role):
        return
    raise PermissionDeniedError(f'Требуется роль: {role.value}')
