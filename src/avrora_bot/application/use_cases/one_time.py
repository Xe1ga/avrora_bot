"""Use case'ы разовых посещений (ТЗ 3.2 п.4)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.application.services.user_lookup import (
    resolve_user,
    resolve_users,
    vk_id_label,
)
from avrora_bot.domain.entities import OneTimePayment, User
from avrora_bot.domain.enums import PaymentStatus, RoleName, TariffKind
from avrora_bot.domain.errors import NotFoundError, ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway
from avrora_bot.domain.value_objects import MonthPeriod

UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class VisitRow:
    """Строка сводки по разовым посещениям."""

    visit: OneTimePayment
    full_name: str
    collector_name: str | None = None


@dataclass(frozen=True, slots=True)
class VisitOutcome:
    """Результат операции над разовым посещением конкретного участника."""

    user: User
    visit: OneTimePayment


class OneTimeUseCases:
    """Регистрация разовых визитов по действующему тарифу месяца."""

    def __init__(self, uow_factory: UowFactory, vk_gateway: VkGateway) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway

    async def register_visits(
        self, actor_vk_id: int, targets: list[str], visit_date: date
    ) -> list[VisitOutcome]:
        """Регистрирует разовые посещения списком (по аналогии с
        ``SubscriptionUseCases.register_voting`` и командой «голоса
        <период>»): сборщик присылает список vk_id/ФИО, посетивших в
        ``visit_date``, каждому заводится отдельная строка оплаты по
        тарифу на эту дату.

        :param targets: vk_id или (часть) ФИО каждого участника — см.
            ``application.services.user_lookup.resolve_users``.
        """
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            tariff = await uow.tariffs.active_for(
                TariffKind.ONE_TIME, visit_date
            )
            if tariff is None:
                raise NotFoundError('Тариф разового посещения не задан')

            users = await resolve_users(uow, targets)
            outcomes: list[VisitOutcome] = []
            for user in users:
                visit = await uow.one_time.add_visit(
                    OneTimePayment(
                        user_id=user.id,
                        visit_date=visit_date,
                        amount=tariff.amount,
                    )
                )
                outcomes.append(VisitOutcome(user=user, visit=visit))
            await record_action(
                uow,
                actor_vk_id,
                'one_time.register_batch',
                f'date={visit_date} user_ids='
                + ','.join(str(u.id) for u in users),
            )
            await uow.commit()
            return outcomes

    async def mark_oldest_unpaid(
        self, actor_vk_id: int, target: str
    ) -> VisitOutcome:
        """Отмечает оплаченным самый старый неоплаченный визит участника.

        :param target: vk_id или (часть) ФИО участника — см.
            ``application.services.user_lookup.resolve_user``.

        :raises NotFoundError: если у участника нет неоплаченных визитов.
        """
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            user = await resolve_user(uow, target)
            unpaid = await uow.one_time.unpaid_visits_of(user.id)
            if not unpaid:
                raise NotFoundError(
                    f'У {user.full_name} нет неоплаченных разовых посещений'
                )
            visit = unpaid[0]  # самый старый — первый по возрастанию даты
            visit.status = PaymentStatus.PAID
            visit.marked_at = datetime.now(UTC)
            visit.collector_vk_id = actor_vk_id
            await uow.one_time.update_visit(visit)
            await record_action(
                uow,
                actor_vk_id,
                'one_time.mark_paid',
                f'user_id={user.id} visit_id={visit.id}',
            )
            await uow.commit()
            return VisitOutcome(user=user, visit=visit)

    async def get_visit(self, actor_vk_id: int, visit_id: int) -> VisitRow:
        """Возвращает запись о разовом посещении для просмотра/правки."""
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            visit = await self._get_visit_or_raise(uow, visit_id)
            return await self._to_row(uow, visit)

    async def set_visit_date(
        self, actor_vk_id: int, visit_id: int, visit_date: date
    ) -> VisitRow:
        """Меняет дату разового посещения."""
        return await self._update_visit(
            actor_vk_id,
            visit_id,
            'one_time.edit_date',
            f'visit_date={visit_date}',
            lambda visit: setattr(visit, 'visit_date', visit_date),
        )

    async def set_visit_amount(
        self, actor_vk_id: int, visit_id: int, amount: Decimal
    ) -> VisitRow:
        """Меняет сумму разового посещения."""
        if amount < 0:
            raise ValidationError('Сумма не может быть отрицательной')
        return await self._update_visit(
            actor_vk_id,
            visit_id,
            'one_time.edit_amount',
            f'amount={amount}',
            lambda visit: setattr(visit, 'amount', amount),
        )

    async def set_visit_status(
        self, actor_vk_id: int, visit_id: int, paid: bool
    ) -> VisitRow:
        """Меняет статус оплаты разового посещения (вручную, по id)."""

        def mutate(visit: OneTimePayment) -> None:
            visit.status = PaymentStatus.PAID if paid else PaymentStatus.UNPAID
            visit.marked_at = datetime.now(UTC) if paid else None
            visit.collector_vk_id = actor_vk_id if paid else None

        return await self._update_visit(
            actor_vk_id,
            visit_id,
            'one_time.edit_status',
            f'paid={paid}',
            mutate,
        )

    async def set_visit_collector(
        self, actor_vk_id: int, visit_id: int, target: str
    ) -> VisitRow:
        """Меняет сборщика, который фактически собрал оплату (collector_vk_id).

        :param target: vk_id или (часть) ФИО сборщика — см.
            ``application.services.user_lookup.resolve_user``.

        Если визит ещё не был отмечен оплаченным, дополнительно переводит
        его в статус «оплачено» и фиксирует текущее время — указывать
        сборщика для неоплаченного визита не имеет смысла. Если визит уже
        оплачен, время приёма (``marked_at``) не трогается — меняется
        только сам сборщик (исправление ошибки атрибуции).

        :raises ValidationError: если указанный сборщик — игрок без
            аккаунта ВК (``collector_vk_id`` хранит именно vk_id, а не
            внутренний id; ``None`` там неотличим от «оплата ещё не
            собрана»).
        """
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            visit = await self._get_visit_or_raise(uow, visit_id)
            collector = await resolve_user(uow, target)
            if collector.vk_id is None:
                raise ValidationError(
                    f'{collector.full_name} добавлен(а) без аккаунта ВК — '
                    'сборщиком оплаты можно указать только участника с ВК'
                )
            visit.collector_vk_id = collector.vk_id
            if visit.status is not PaymentStatus.PAID:
                visit.status = PaymentStatus.PAID
                visit.marked_at = datetime.now(UTC)
            await uow.one_time.update_visit(visit)
            await record_action(
                uow,
                actor_vk_id,
                'one_time.edit_collector',
                f'visit_id={visit_id} collector_vk_id={collector.vk_id}',
            )
            await uow.commit()
            return await self._to_row(uow, visit)

    async def delete_visit(self, actor_vk_id: int, visit_id: int) -> None:
        """Удаляет запись о разовом посещении по id."""
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            await self._get_visit_or_raise(uow, visit_id)
            await uow.one_time.delete_visit(visit_id)
            await record_action(
                uow,
                actor_vk_id,
                'one_time.delete_visit',
                f'visit_id={visit_id}',
            )
            await uow.commit()

    async def month_visits(self, period: MonthPeriod) -> list[VisitRow]:
        """Список разовых посещений за месяц с именами участников.

        Для оплаченных визитов дополнительно резолвит ``collector_vk_id``
        в ФИО — кто фактически собрал деньги (ТЗ 3.2), чтобы это было
        видно прямо в сводке, а не только в журнале действий.
        """
        async with self._uow_factory() as uow:
            visits = await uow.one_time.visits_in_month(period)
            return [await self._to_row(uow, visit) for visit in visits]

    async def _update_visit(
        self,
        actor_vk_id: int,
        visit_id: int,
        action: str,
        details: str,
        mutate: Callable[[OneTimePayment], None],
    ) -> VisitRow:
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            visit = await self._get_visit_or_raise(uow, visit_id)
            mutate(visit)
            await uow.one_time.update_visit(visit)
            await record_action(
                uow, actor_vk_id, action, f'visit_id={visit_id} {details}'
            )
            await uow.commit()
            return await self._to_row(uow, visit)

    @staticmethod
    async def _get_visit_or_raise(
        uow: UnitOfWork, visit_id: int
    ) -> OneTimePayment:
        visit = await uow.one_time.get_visit(visit_id)
        if visit is None:
            raise NotFoundError('Разовое посещение не найдено')
        return visit

    @staticmethod
    async def _to_row(uow: UnitOfWork, visit: OneTimePayment) -> VisitRow:
        user = await uow.users.get_by_id(visit.user_id)
        name = user.full_name if user else f'id{visit.user_id}'
        collector_name = None
        if visit.collector_vk_id is not None:
            collector = await uow.users.get_by_vk_id(visit.collector_vk_id)
            collector_name = (
                collector.full_name
                if collector
                else vk_id_label(visit.collector_vk_id)
            )
        return VisitRow(
            visit=visit, full_name=name, collector_name=collector_name
        )
