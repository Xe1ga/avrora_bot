"""Use case'ы управления тарифами (ТЗ 3.2.1, 3.2 п.4)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.domain.entities import Tariff
from avrora_bot.domain.enums import RoleName, TariffKind
from avrora_bot.domain.errors import NotFoundError, ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway

UowFactory = Callable[[], UnitOfWork]


class TariffUseCases:
    """Редактирование тарифов зала/тренера/разового посещения.

    Изменять тарифы вправе администратор и сборщик платежей (ТЗ 2).
    Новое значение сохраняется как новая запись с датой начала действия —
    история изменений не теряется.
    """

    def __init__(self, uow_factory: UowFactory, vk_gateway: VkGateway) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway

    async def set_tariff(
        self,
        actor_vk_id: int,
        kind: TariffKind,
        amount: Decimal,
        valid_from: date,
    ) -> Tariff:
        """Устанавливает новое значение тарифа с указанной даты."""
        if amount < 0:
            raise ValidationError('Сумма тарифа не может быть отрицательной')
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            tariff = await uow.tariffs.add(
                Tariff(kind=kind, amount=amount, valid_from=valid_from)
            )
            await record_action(
                uow,
                actor_vk_id,
                'tariff.set',
                f'kind={kind.value} amount={amount} from={valid_from}',
            )
            await uow.commit()
            return tariff

    async def get_active(self, kind: TariffKind, on_date: date) -> Tariff:
        """Возвращает действующий тариф на дату.

        :raises NotFoundError: если тариф не задан.
        """
        async with self._uow_factory() as uow:
            tariff = await uow.tariffs.active_for(kind, on_date)
            if tariff is None:
                raise NotFoundError(f'Тариф {kind.value} на {on_date} не задан')
            return tariff
