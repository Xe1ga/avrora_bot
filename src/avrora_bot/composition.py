"""Сборка зависимостей (composition root).

Единственное место, где конкретные реализации адаптеров связываются с
use case'ами и ботом. Остальной код зависит только от абстракций.
"""

from dataclasses import dataclass
from pathlib import Path

from vkbottle import API, Bot

from avrora_bot.adapters.database.crypto import PiiCipher, decode_pii_key
from avrora_bot.adapters.database.engine import (
    create_engine,
    create_session_factory,
)
from avrora_bot.adapters.database.unit_of_work import SqlAlchemyUnitOfWork
from avrora_bot.adapters.vk.bot import build_bot
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.gateway import VkbottleGateway
from avrora_bot.application.use_cases.calendar import CalendarUseCases
from avrora_bot.application.use_cases.one_time import OneTimeUseCases
from avrora_bot.application.use_cases.registration import RegistrationUseCases
from avrora_bot.application.use_cases.reports import ReportUseCases
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.application.use_cases.subscriptions import SubscriptionUseCases
from avrora_bot.application.use_cases.tariffs import TariffUseCases
from avrora_bot.application.use_cases.user_management import (
    UserManagementUseCases,
)
from avrora_bot.config import Settings
from avrora_bot.domain.ports.uow import UnitOfWork


@dataclass(slots=True)
class Container:
    """Собранные компоненты приложения."""

    settings: Settings
    engine: object  # AsyncEngine
    uow_factory: object  # Callable[[], UnitOfWork]
    gateway: VkbottleGateway
    bot: Bot
    report_dir: Path


def build_container(settings: Settings) -> Container:
    """Создаёт все компоненты приложения из настроек."""
    engine = create_engine(settings.database_dsn)
    session_factory = create_session_factory(engine)
    cipher = PiiCipher(
        decode_pii_key(settings.pii_encryption_key.get_secret_value())
    )

    def uow_factory() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, cipher)

    # Единый VK API-клиент для бота и шлюза проверки прав.
    api = API(settings.vk_token.get_secret_value())
    gateway = VkbottleGateway(api, settings.vk_group_id)

    registration = RegistrationUseCases(uow_factory, gateway)
    subscriptions = SubscriptionUseCases(uow_factory, gateway)
    ctx = BotContext(
        registration=registration,
        roles=RoleUseCases(uow_factory, gateway),
        tariffs=TariffUseCases(uow_factory, gateway),
        subscriptions=subscriptions,
        one_time=OneTimeUseCases(uow_factory, gateway),
        calendar=CalendarUseCases(uow_factory, gateway),
        reports=ReportUseCases(uow_factory, subscriptions),
        user_management=UserManagementUseCases(uow_factory, gateway),
    )

    report_dir = Path('/tmp/avrora_reports')
    bot = build_bot(
        api=api,
        ctx=ctx,
        gateway=gateway,
        rate_limit_per_sec=settings.rate_limit_per_sec,
        report_dir=report_dir,
        privacy_policy_url=settings.privacy_policy_url,
        pdn_consent_url=settings.pdn_consent_url,
        pdn_consent_version=settings.pdn_consent_version,
    )

    return Container(
        settings=settings,
        engine=engine,
        uow_factory=uow_factory,
        gateway=gateway,
        bot=bot,
        report_dir=report_dir,
    )
