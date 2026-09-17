"""Use case'ы разовых посещений (ТЗ 3.2 п.4)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.application.services.user_lookup import resolve_user
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
    marked_by_name: str | None = None


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
            ``application.services.user_lookup.resolve_user``.

        Список резолвится целиком и только затем сохраняется: если хотя бы
        один vk_id/ФИО не найден или неоднозначен, весь список отклоняется
        — иначе часть посещений уже была бы записана, а сборщику пришлось
        бы разбираться, кто из уже зарегистрированных лишний.
        """
        unique_targets = list(dict.fromkeys(t.strip() for t in targets if t.strip()))
        if not unique_targets:
            raise ValidationError('Список пуст')
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            tariff = await uow.tariffs.active_for(
                TariffKind.ONE_TIME, visit_date
            )
            if tariff is None:
                raise NotFoundError('Тариф разового посещения не задан')

            resolved: list[User] = []
            errors: list[str] = []
            for target in unique_targets:
                try:
                    resolved.append(await resolve_user(uow, target))
                except (NotFoundError, ValidationError) as exc:
                    errors.append(f'«{target}»: {exc}')
            if errors:
                raise ValidationError('\n'.join(errors))

            users: list[User] = []
            seen_ids: set[int] = set()
            for user in resolved:
                if user.id not in seen_ids:
                    seen_ids.add(user.id)
                    users.append(user)

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
                f'date={visit_date} vk_ids='
                + ','.join(str(u.vk_id) for u in users),
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
            visit.marked_by_vk_id = actor_vk_id
            await uow.one_time.update_visit(visit)
            await record_action(
                uow,
                actor_vk_id,
                'one_time.mark_paid',
                f'vk_id={user.vk_id} visit_id={visit.id}',
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
            visit.marked_by_vk_id = actor_vk_id if paid else None

        return await self._update_visit(
            actor_vk_id,
            visit_id,
            'one_time.edit_status',
            f'paid={paid}',
            mutate,
        )

    async def set_visit_marked_by(
        self, actor_vk_id: int, visit_id: int, target: str
    ) -> VisitRow:
        """Меняет, кто принял оплату разового посещения (marked_by_vk_id).

        :param target: vk_id или (часть) ФИО получателя оплаты — см.
            ``application.services.user_lookup.resolve_user``.

        Если визит ещё не был отмечен оплаченным, дополнительно переводит
        его в статус «оплачено» и фиксирует текущее время — указывать,
        кто принял деньги, для неоплаченного визита не имеет смысла.
        Если визит уже оплачен, время приёма (``marked_at``) не трогается
        — меняется только сам получатель (исправление ошибки атрибуции).
        """
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            visit = await self._get_visit_or_raise(uow, visit_id)
            receiver = await resolve_user(uow, target)
            visit.marked_by_vk_id = receiver.vk_id
            if visit.status is not PaymentStatus.PAID:
                visit.status = PaymentStatus.PAID
                visit.marked_at = datetime.now(UTC)
            await uow.one_time.update_visit(visit)
            await record_action(
                uow,
                actor_vk_id,
                'one_time.edit_marked_by',
                f'visit_id={visit_id} marked_by_vk_id={receiver.vk_id}',
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

        Для оплаченных визитов дополнительно резолвит ``marked_by_vk_id``
        в ФИО — кому сборщик передал деньги (ТЗ 3.2), чтобы это было
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
        marked_by_name = None
        if visit.marked_by_vk_id is not None:
            marker = await uow.users.get_by_vk_id(visit.marked_by_vk_id)
            marked_by_name = (
                marker.full_name
                if marker
                else f'vk_id {visit.marked_by_vk_id}'
            )
        return VisitRow(
            visit=visit, full_name=name, marked_by_name=marked_by_name
        )
