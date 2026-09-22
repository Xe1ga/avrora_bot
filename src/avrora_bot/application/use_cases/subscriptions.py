"""Use case'ы учёта абонементов (ТЗ 3.2).

Сценарий: сборщик вручную вносит список проголосовавших → бот считает сумму
на человека (тариф месяца / число проголосовавших, округление вверх) →
сборщик при желании переопределяет сумму → фиксирует оплаты по факту.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.application.services.user_lookup import (
    resolve_user,
    resolve_users,
    vk_id_label,
)
from avrora_bot.domain.entities import Subscription, SubscriptionPayment, User
from avrora_bot.domain.enums import PaymentStatus, RoleName, TariffKind
from avrora_bot.domain.errors import NotFoundError, ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway
from avrora_bot.domain.services.subscription_calc import per_person
from avrora_bot.domain.services.tariff_calc import MonthCost, month_cost
from avrora_bot.domain.value_objects import MonthPeriod

UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class MonthCalculation:
    """Результат расчёта суммы абонемента (до фиксации)."""

    period: MonthPeriod
    cost: MonthCost
    voters: int
    per_person_amount: Decimal


@dataclass(frozen=True, slots=True)
class PaymentRow:
    """Строка сводки по оплате участника."""

    user: User
    status: PaymentStatus
    collector_name: str | None = None


@dataclass(frozen=True, slots=True)
class VoterChange:
    """Результат добавления/удаления проголосовавшего."""

    subscription: Subscription
    user: User


@dataclass(frozen=True, slots=True)
class MonthSummary:
    """Итоговая сводка по месяцу."""

    subscription: Subscription
    rows: list[PaymentRow]

    @property
    def paid_count(self) -> int:
        return sum(1 for r in self.rows if r.status is PaymentStatus.PAID)

    @property
    def collected(self) -> Decimal:
        return self.subscription.effective_amount * self.paid_count


class SubscriptionUseCases:
    """Голосование, расчёт, фиксация оплат и сводка по месяцу."""

    def __init__(self, uow_factory: UowFactory, vk_gateway: VkGateway) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway

    async def _month_cost(
        self, uow: UnitOfWork, period: MonthPeriod
    ) -> MonthCost:
        """Считает стоимость месяца по тарифам и расписанию."""
        hall = await uow.tariffs.active_for(
            TariffKind.HALL_HOUR, period.first_day
        )
        coach = await uow.tariffs.active_for(
            TariffKind.COACH_SESSION, period.first_day
        )
        if hall is None or coach is None:
            raise NotFoundError('Не заданы тарифы зала/тренера на этот месяц')
        schedule = await uow.schedule.active_slots()
        return month_cost(period, schedule, hall.amount, coach.amount)

    async def calculate(
        self, actor_vk_id: int, period: MonthPeriod, voters: int
    ) -> MonthCalculation:
        """Предварительный расчёт суммы на человека (без сохранения)."""
        if voters <= 0:
            raise ValidationError('Число проголосовавших должно быть > 0')
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            cost = await self._month_cost(uow, period)
            return MonthCalculation(
                period=period,
                cost=cost,
                voters=voters,
                per_person_amount=per_person(cost.total, voters),
            )

    async def register_voting(
        self,
        actor_vk_id: int,
        period: MonthPeriod,
        voters: list[str],
        override_amount: Decimal | None = None,
    ) -> Subscription:
        """Фиксирует голосование: создаёт подписку и строки оплат.

        :param voters: vk_id или (часть) ФИО каждого проголосовавшего —
            см. ``application.services.user_lookup.resolve_users``.
        :param override_amount: ручная сумма на человека (приоритет над
            авторасчётом — итоговое решение за сборщиком, ТЗ 3.2 п.2).
        """
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            if await uow.subscriptions.get_for_month(period) is not None:
                raise ValidationError(
                    f'Подписка на {period.label()} уже существует'
                )
            cost = await self._month_cost(uow, period)
            users = await resolve_users(uow, voters)
            voters_count = len(users)
            amount = (
                override_amount
                if override_amount is not None
                else per_person(cost.total, voters_count)
            )

            subscription = await uow.subscriptions.create(
                Subscription(
                    period_year=period.year,
                    period_month=period.month,
                    total_amount=cost.total,
                    voters_count=voters_count,
                    per_person_amount=amount,
                )
            )
            for user in users:
                await uow.subscriptions.add_payment(
                    SubscriptionPayment(
                        subscription_id=subscription.id, user_id=user.id
                    )
                )
            await record_action(
                uow,
                actor_vk_id,
                'subscription.register',
                f'{period} voters={voters_count} amount={amount}',
            )
            await uow.commit()
            return subscription

    async def set_fact_amount(
        self, actor_vk_id: int, period: MonthPeriod, amount: Decimal
    ) -> Subscription:
        """Фиксирует фактическую сумму абонемента, собираемую с человека.

        В отличие от расчётной ``per_person_amount`` (тарифы / число
        голосов), эта сумма не пересчитывается при изменении списка
        проголосовавших и приоритетна во всех отчётах по сдаче средств
        (``Subscription.effective_amount``, ТЗ 3.2).
        """
        if amount < 0:
            raise ValidationError('Сумма не может быть отрицательной')
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            subscription = await uow.subscriptions.get_for_month(period)
            if subscription is None:
                raise NotFoundError('Подписка на месяц не найдена')
            subscription.per_percent_amount_fact = amount
            await uow.subscriptions.update(subscription)
            await record_action(
                uow,
                actor_vk_id,
                'subscription.set_fact_amount',
                f'{period} amount={amount}',
            )
            await uow.commit()
            return subscription

    async def mark_payment(
        self,
        actor_vk_id: int,
        period: MonthPeriod,
        target: str,
        paid: bool,
    ) -> User:
        """Отмечает факт оплаты абонемента участником.

        :param target: vk_id или (часть) ФИО участника — см.
            ``application.services.user_lookup.resolve_user``.
        """
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            subscription = await uow.subscriptions.get_for_month(period)
            if subscription is None:
                raise NotFoundError('Подписка на месяц не найдена')
            user = await resolve_user(uow, target)
            payment = await uow.subscriptions.get_payment(
                subscription.id, user.id
            )
            if payment is None:
                raise NotFoundError(
                    'Участник не входит в список проголосовавших'
                )
            payment.status = (
                PaymentStatus.PAID if paid else PaymentStatus.UNPAID
            )
            payment.marked_at = datetime.now(UTC) if paid else None
            payment.collector_vk_id = actor_vk_id if paid else None
            await uow.subscriptions.update_payment(payment)
            await record_action(
                uow,
                actor_vk_id,
                'subscription.mark_payment',
                f'{period} user_id={user.id} paid={paid}',
            )
            await uow.commit()
            return user

    async def mark_payments_bulk(
        self,
        actor_vk_id: int,
        period: MonthPeriod,
        user_ids: list[int],
        *,
        paid: bool,
    ) -> list[User]:
        """Отмечает оплату сразу для нескольких участников одной транзакцией.

        Используется чекбокс-клавиатурой в «Абонементах» (мультивыбор
        неоплативших + «Отметить оплаченными») — та же логика по каждому,
        что и в ``mark_payment``, но без отдельного запроса на человека.
        ``user_ids`` без записи в подписке (например, участника убрали из
        списка проголосовавших, пока диалог был открыт) молча пропускаются.
        """
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            subscription = await uow.subscriptions.get_for_month(period)
            if subscription is None:
                raise NotFoundError('Подписка на месяц не найдена')
            marked: list[User] = []
            for user_id in user_ids:
                payment = await uow.subscriptions.get_payment(
                    subscription.id, user_id
                )
                if payment is None:
                    continue
                payment.status = (
                    PaymentStatus.PAID if paid else PaymentStatus.UNPAID
                )
                payment.marked_at = datetime.now(UTC) if paid else None
                payment.collector_vk_id = actor_vk_id if paid else None
                await uow.subscriptions.update_payment(payment)
                user = await uow.users.get_by_id(user_id)
                if user is not None:
                    marked.append(user)
            if marked:
                await record_action(
                    uow,
                    actor_vk_id,
                    'subscription.mark_payment_bulk',
                    f'{period} user_ids={[u.id for u in marked]} paid={paid}',
                )
                await uow.commit()
            return marked

    async def add_voter(
        self, actor_vk_id: int, period: MonthPeriod, target: str
    ) -> VoterChange:
        """Добавляет проголосовавшего в уже существующую подписку.

        :param target: vk_id или (часть) ФИО участника — см.
            ``application.services.user_lookup.resolve_user``.

        Расчётная сумма на человека (``per_person_amount``) пересчитывается
        автоматически по новому числу голосов; фактическая сумма сборщика
        (``per_percent_amount_fact``), если она была зафиксирована, не
        трогается.
        """
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            subscription = await uow.subscriptions.get_for_month(period)
            if subscription is None:
                raise NotFoundError('Подписка на месяц не найдена')
            user = await resolve_user(uow, target)
            existing = await uow.subscriptions.get_payment(
                subscription.id, user.id
            )
            if existing is not None:
                raise ValidationError(
                    'Этот участник уже в списке проголосовавших'
                )
            await uow.subscriptions.add_payment(
                SubscriptionPayment(
                    subscription_id=subscription.id, user_id=user.id
                )
            )
            subscription.voters_count += 1
            subscription.per_person_amount = per_person(
                subscription.total_amount, subscription.voters_count
            )
            await uow.subscriptions.update(subscription)
            await record_action(
                uow,
                actor_vk_id,
                'subscription.add_voter',
                f'{period} user_id={user.id}',
            )
            await uow.commit()
            return VoterChange(subscription=subscription, user=user)

    async def remove_voter(
        self, actor_vk_id: int, period: MonthPeriod, target: str
    ) -> VoterChange:
        """Убирает проголосовавшего из подписки (например, ввели по ошибке).

        :param target: vk_id или (часть) ФИО участника — см.
            ``application.services.user_lookup.resolve_user``.

        Расчётная сумма на человека (``per_person_amount``) пересчитывается
        автоматически по новому числу голосов; фактическая сумма сборщика
        (``per_percent_amount_fact``), если она была зафиксирована, не
        трогается.
        """
        async with self._uow_factory() as uow:
            await permissions.require_role(
                uow, self._vk, actor_vk_id, RoleName.COLLECTOR
            )
            subscription = await uow.subscriptions.get_for_month(period)
            if subscription is None:
                raise NotFoundError('Подписка на месяц не найдена')
            user = await resolve_user(uow, target)
            payment = await uow.subscriptions.get_payment(
                subscription.id, user.id
            )
            if payment is None:
                raise NotFoundError(
                    'Участник не входит в список проголосовавших'
                )
            if subscription.voters_count <= 1:
                raise ValidationError(
                    'Нельзя удалить последнего проголосовавшего из подписки'
                )
            await uow.subscriptions.delete_payment(payment.id)
            subscription.voters_count -= 1
            subscription.per_person_amount = per_person(
                subscription.total_amount, subscription.voters_count
            )
            await uow.subscriptions.update(subscription)
            await record_action(
                uow,
                actor_vk_id,
                'subscription.remove_voter',
                f'{period} user_id={user.id}',
            )
            await uow.commit()
            return VoterChange(subscription=subscription, user=user)

    async def month_summary(self, period: MonthPeriod) -> MonthSummary:
        """Строит сводку по месяцу (для отчётов и списка в «Абонементах»).

        Для оплаченных строк дополнительно резолвит ``collector_vk_id`` в
        ФИО — кто фактически собрал деньги (ТЗ 3.2), как и в разовых
        посещениях (``OneTimeUseCases.month_visits``).
        """
        async with self._uow_factory() as uow:
            subscription = await uow.subscriptions.get_for_month(period)
            if subscription is None:
                raise NotFoundError('Подписка на месяц не найдена')
            payments = await uow.subscriptions.payments_of(subscription.id)
            rows: list[PaymentRow] = []
            for payment in payments:
                user = await uow.users.get_by_id(payment.user_id)
                if user is None:
                    continue
                collector_name = None
                if payment.collector_vk_id is not None:
                    collector = await uow.users.get_by_vk_id(
                        payment.collector_vk_id
                    )
                    collector_name = (
                        collector.full_name
                        if collector
                        else vk_id_label(payment.collector_vk_id)
                    )
                rows.append(
                    PaymentRow(
                        user=user,
                        status=payment.status,
                        collector_name=collector_name,
                    )
                )
            rows.sort(key=lambda r: r.user.full_name)
            return MonthSummary(subscription=subscription, rows=rows)

