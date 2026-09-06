"""Use case'ы разовых посещений (ТЗ 3.2 п.4)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.domain.entities import OneTimePayment
from avrora_bot.domain.enums import PaymentStatus, RoleName, TariffKind
from avrora_bot.domain.errors import NotFoundError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway
from avrora_bot.domain.value_objects import MonthPeriod

UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class VisitRow:
    """Строка сводки по разовым посещениям."""

    visit: OneTimePayment
    full_name: str


class OneTimeUseCases:
    """Регистрация разовых визитов по действующему тарифу месяца."""

    def __init__(self, uow_factory: UowFactory, vk_gateway: VkGateway) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway

    async def register_visit(
        self, actor_vk_id: int, target_vk_id: int, visit_date: date
    ) -> OneTimePayment:
        """Регистрирует разовое посещение по тарифу на дату визита."""
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            user = await uow.users.get_by_vk_id(target_vk_id)
            if user is None:
                raise NotFoundError('Пользователь не найден')
            tariff = await uow.tariffs.active_for(
                TariffKind.ONE_TIME, visit_date
            )
            if tariff is None:
                raise NotFoundError('Тариф разового посещения не задан')
            visit = await uow.one_time.add_visit(
                OneTimePayment(
                    user_id=user.id,
                    visit_date=visit_date,
                    amount=tariff.amount,
                )
            )
            await record_action(
                uow,
                actor_vk_id,
                'one_time.register',
                f'vk_id={target_vk_id} date={visit_date} amount={tariff.amount}',
            )
            await uow.commit()
            return visit

    async def mark_paid(
        self, actor_vk_id: int, visit_id: int, paid: bool
    ) -> None:
        """Отмечает оплату разового посещения."""
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            visit = await uow.one_time.get_visit(visit_id)
            if visit is None:
                raise NotFoundError('Разовое посещение не найдено')
            visit.status = PaymentStatus.PAID if paid else PaymentStatus.UNPAID
            visit.marked_at = datetime.now(UTC) if paid else None
            visit.marked_by_vk_id = actor_vk_id if paid else None
            await uow.one_time.update_visit(visit)
            await record_action(
                uow,
                actor_vk_id,
                'one_time.mark_paid',
                f'visit_id={visit_id} paid={paid}',
            )
            await uow.commit()

    async def month_visits(self, period: MonthPeriod) -> list[VisitRow]:
        """Список разовых посещений за месяц с именами участников."""
        async with self._uow_factory() as uow:
            visits = await uow.one_time.visits_in_month(period)
            rows: list[VisitRow] = []
            for visit in visits:
                user = await uow.users.get_by_id(visit.user_id)
                name = user.full_name if user else f'id{visit.user_id}'
                rows.append(VisitRow(visit=visit, full_name=name))
            return rows
