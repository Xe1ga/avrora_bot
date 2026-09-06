"""Идемпотентный сидинг справочных данных.

Наполняет БД начальными тарифами и недельным расписанием (по данным файла
«Оплата абонементов.md»), а также при необходимости назначает первого
администратора (bootstrap). Вызывается при старте приложения после миграций.
"""

from datetime import date, time
from decimal import Decimal

from avrora_bot.domain import entities as e
from avrora_bot.domain.enums import RoleName, TariffKind, UserStatus, Weekday
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.logging_setup import get_logger

log = get_logger('seed')

# Начало расчётного периода (сентябрь 2026) — дата начала действия тарифов.
_PERIOD_START = date(2026, 9, 1)

# Тарифы по умолчанию (₽): зал/час, тренер/тренировка, разовое посещение.
_DEFAULT_TARIFFS: tuple[tuple[TariffKind, Decimal], ...] = (
    (TariffKind.HALL_HOUR, Decimal('1250')),
    (TariffKind.COACH_SESSION, Decimal('1500')),
    (TariffKind.ONE_TIME, Decimal('350')),
)

# Недельное расписание: Вт 19:00-20:30 и 20:30-22:00, Чт 19:30-21:30, Пт 19:00-21:00.
_DEFAULT_SCHEDULE: tuple[tuple[Weekday, time, time], ...] = (
    (Weekday.TUESDAY, time(19, 0), time(20, 30)),
    (Weekday.TUESDAY, time(20, 30), time(22, 0)),
    (Weekday.THURSDAY, time(19, 30), time(21, 30)),
    (Weekday.FRIDAY, time(19, 0), time(21, 0)),
)


async def seed_reference_data(uow: UnitOfWork) -> None:
    """Создаёт начальные тарифы и расписание, если их ещё нет."""
    for kind, amount in _DEFAULT_TARIFFS:
        existing = await uow.tariffs.active_for(kind, _PERIOD_START)
        if existing is None:
            await uow.tariffs.add(
                e.Tariff(kind=kind, amount=amount, valid_from=_PERIOD_START)
            )
            log.info('seed.tariff', kind=str(kind), amount=str(amount))

    slots = await uow.schedule.active_slots()
    if not slots:
        for weekday, start, end in _DEFAULT_SCHEDULE:
            await uow.schedule.add(
                e.ScheduleSlot(weekday=weekday, start=start, end=end)
            )
        log.info('seed.schedule', slots=len(_DEFAULT_SCHEDULE))


async def ensure_bootstrap_admin(
    uow: UnitOfWork, admin_vk_id: int | None
) -> None:
    """Гарантирует наличие первого администратора.

    Если задан ``BOOTSTRAP_ADMIN_VK_ID``, создаёт (при отсутствии) профиль
    и назначает роль ``admin``. Профиль сразу активен, чтобы администратор
    мог управлять остальными.
    """
    if admin_vk_id is None:
        return
    user = await uow.users.get_by_vk_id(admin_vk_id)
    if user is None:
        user = await uow.users.add(
            e.User(
                vk_id=admin_vk_id,
                full_name='Администратор',
                status=UserStatus.ACTIVE,
            )
        )
        log.info('seed.bootstrap_admin.created', vk_id=admin_vk_id)
    elif user.status is not UserStatus.ACTIVE:
        user.status = UserStatus.ACTIVE
        await uow.users.update(user)
    await uow.roles.assign(user.id, RoleName.ADMIN)
    log.info('seed.bootstrap_admin.role_assigned', vk_id=admin_vk_id)
