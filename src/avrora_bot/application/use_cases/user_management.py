"""Use case'ы просмотра и редактирования данных пользователя администратором."""

from collections.abc import Callable
from datetime import date

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.domain.entities import User
from avrora_bot.domain.enums import RoleName, UserStatus
from avrora_bot.domain.errors import NotFoundError, ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway

UowFactory = Callable[[], UnitOfWork]
_Mutator = Callable[[User], None]

# Замена ФИО при уничтожении персональных данных (152-ФЗ, отзыв согласия).
# Само шифрованное значение перезаписывается этой строкой — восстановить
# исходное ФИО из БД после этого невозможно.
_ANONYMIZED_FULL_NAME = 'Пользователь удалил персональные данные'


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

    async def list_players(self, actor_vk_id: int) -> list[User]:
        """Возвращает всех игроков (роль ``player``) с их данными.

        Доступно администратору, сборщику и куратору — им нужен общий
        список участников (ФИО, ДР, рост, телефон, vk_id), а не только
        точечный просмотр/правка одного профиля (``get_user``).
        """
        async with self._uow_factory() as uow:
            await permissions.require_any_role(
                uow,
                self._vk,
                actor_vk_id,
                (RoleName.ADMIN, RoleName.COLLECTOR, RoleName.CURATOR),
            )
            players = await uow.roles.users_with_role(RoleName.PLAYER)
            return sorted(players, key=lambda user: user.full_name)

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

    async def delete_personal_data(
        self, admin_vk_id: int, target_vk_id: int
    ) -> User:
        """
        Уничтожает персональные данные пользователя (ТЗ 3.6, 152-ФЗ ст. 21):
        удовлетворяет отзыву согласия на обработку. ФИО перезаписывается
        меткой (шифрованное значение необратимо теряется), телефон/дата
        рождения/рост обнуляются, все роли снимаются, статус — ``deleted``.

        Не трогаются: vk_id (публичен в самом VK, не тайна, которую хранит
        бот), история оплат/посещений (``subscription_payments``,
        ``one_time_payments`` — это факты «оплатил/не оплатил», не ФИО) и
        журнал согласий ``user_consents`` (доказательство правомерности
        прошлой обработки и самого факта отзыва — нужен оператору для
        защиты при проверке).

        :raises NotFoundError: если пользователь с таким vk_id не найден.
        :raises ValidationError: если данные уже были уничтожены ранее.
        """
        async with self._uow_factory() as uow:
            await permissions.require_admin(uow, self._vk, admin_vk_id)
            user = await self._get_or_raise(uow, target_vk_id)
            if user.status is UserStatus.DELETED:
                raise ValidationError(
                    'Персональные данные этого пользователя уже удалены'
                )
            user.full_name = _ANONYMIZED_FULL_NAME
            user.phone = None
            user.birthdate = None
            user.height_cm = None
            user.status = UserStatus.DELETED
            await uow.users.update(user)
            for role in await uow.roles.roles_of(user.id):
                await uow.roles.revoke(user.id, role)
            user.roles = set()  # отражаем снятые роли в возвращаемой сущности
            await record_action(
                uow,
                admin_vk_id,
                'user.delete_personal_data',
                f'vk_id={target_vk_id}',
            )
            await uow.commit()
            return user

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
