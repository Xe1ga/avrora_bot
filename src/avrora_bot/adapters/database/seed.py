"""Идемпотентный сидинг справочных данных.

Наполняет БД начальными тарифами и недельным расписанием (по данным файла
«Оплата абонементов.md»), регистрирует актуальные версии юридических
документов из ``docs/legal/``, а также при необходимости назначает первого
администратора (bootstrap). Вызывается при старте приложения после миграций.
"""

from datetime import date, time
from decimal import Decimal
from pathlib import Path

from avrora_bot.adapters.legal.files import load_document
from avrora_bot.domain import entities as e
from avrora_bot.domain.enums import (
    LegalDocumentKind,
    RoleName,
    TariffKind,
    UserStatus,
    Weekday,
)
from avrora_bot.domain.errors import ValidationError
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

# Недельное расписание: Вт 19:00-20:30 и 20:30-22:00, Чт 19:30-21:30, Пт 19:00-21:00
# — с местом/тренером по умолчанию для автогенерации тренировок месяца.
_PLACE_VOLKOVA = '15 школа, тренер Волкова Елена'
_PLACE_KRYLOV = '15 школа, тренер Крылов Дмитрий'
_DEFAULT_SCHEDULE: tuple[tuple[Weekday, time, time, str], ...] = (
    (Weekday.TUESDAY, time(19, 0), time(20, 30), _PLACE_VOLKOVA),
    (Weekday.TUESDAY, time(20, 30), time(22, 0), _PLACE_KRYLOV),
    (Weekday.THURSDAY, time(19, 30), time(21, 30), _PLACE_KRYLOV),
    (Weekday.FRIDAY, time(19, 0), time(21, 0), _PLACE_VOLKOVA),
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
        for weekday, start, end, place in _DEFAULT_SCHEDULE:
            await uow.schedule.add(
                e.ScheduleSlot(
                    weekday=weekday, start=start, end=end, place=place
                )
            )
        log.info('seed.schedule', slots=len(_DEFAULT_SCHEDULE))


async def sync_legal_documents(
    uow: UnitOfWork,
    docs_dir: Path,
    *,
    urls: dict[LegalDocumentKind, str] | None = None,
) -> None:
    """Регистрирует версии документов из ``docs/legal/`` (идемпотентно).

    Для каждого документа читается файл, из заголовка берётся номер версии,
    и если такой версии в ``legal_documents`` ещё нет — добавляется новая
    строка с полным текстом и sha256. Уже зарегистрированные версии не
    трогаются: на них ссылается журнал согласий, текст должен остаться
    ровно таким, каким его принимали пользователи.

    Если текст файла изменился без подъёма номера версии, расхождение
    хэшей пишется в лог как предупреждение — в БД остаётся ранее
    зафиксированный текст, а новую редакцию нужно публиковать с новой
    версией в заголовке.

    Отсутствие или неразбираемость файла не останавливает приложение:
    ошибка логируется, а регистрация новых пользователей будет отклонена
    (см. ``application.use_cases.legal``), пока документы не появятся.
    """
    urls = urls or {}
    for kind in LegalDocumentKind:
        try:
            document = load_document(kind, docs_dir, urls.get(kind))
        except (OSError, ValidationError) as exc:
            log.error(
                'seed.legal_document.unavailable',
                kind=str(kind),
                dir=str(docs_dir),
                error=str(exc),
            )
            continue
        existing = await uow.legal_documents.get_by_version(
            kind, document.version
        )
        if existing is None:
            await uow.legal_documents.add(document)
            log.info(
                'seed.legal_document.registered',
                kind=str(kind),
                version=document.version,
            )
        elif existing.sha256 != document.sha256:
            log.warning(
                'seed.legal_document.changed_without_new_version',
                kind=str(kind),
                version=document.version,
                stored_sha256=existing.sha256,
                file_sha256=document.sha256,
            )


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
