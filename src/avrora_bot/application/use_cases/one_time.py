"""Use case'ы разовых посещений (ТЗ 3.2 п.4)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

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
