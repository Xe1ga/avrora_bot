"""Проверка прав доступа НА МОМЕНТ ВЫПОЛНЕНИЯ (ТЗ 5.2).

Права не кэшируются: роль администратора верифицируется через VK API при
каждом действии, прочие роли читаются из БД в текущей транзакции.
"""

from collections.abc import Iterable

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


def has_access(roles: frozenset[RoleName], role: RoleName) -> bool:
    """Проверяет доступ к ролевому разделу UI по уже вычисленным ролям.

    Администратор имеет доступ ко всем ролевым разделам (ТЗ 2: «Полный
    доступ ко всем функциям бота»), даже если явной роли ``admin`` нет
    среди ``roles`` (см. ``effective_roles``, которая уже её туда
    добавляет для администраторов сообщества VK).
    """
    return RoleName.ADMIN in roles or role in roles


async def effective_roles(
    uow: UnitOfWork, vk_gateway: VkGateway, vk_id: int
) -> frozenset[RoleName]:
    """Возвращает полный набор ролей пользователя для построения UI.

    Объединяет роли, назначенные в БД, с ролью ``admin``, если пользователь —
    администратор сообщества VK (см. ``is_admin``): у такого администратора
    роль ``admin`` может отсутствовать в БД, но право есть.
    """
    user = await uow.users.get_by_vk_id(vk_id)
    roles = set(user.roles) if user else set()
    if await vk_gateway.is_group_admin(vk_id):
        roles.add(RoleName.ADMIN)
    return frozenset(roles)


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


async def require_any_role(
    uow: UnitOfWork,
    vk_gateway: VkGateway,
    vk_id: int,
    roles: Iterable[RoleName],
) -> None:
    """Проверяет наличие хотя бы одной из ролей; админ имеет доступ ко всему.

    :raises PermissionDeniedError: если прав недостаточно.
    """
    if await is_admin(uow, vk_gateway, vk_id):
        return
    for role in roles:
        if await has_role(uow, vk_id, role):
            return
    names = ', '.join(role.value for role in roles)
    raise PermissionDeniedError(f'Требуется одна из ролей: {names}')
