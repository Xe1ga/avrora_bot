"""Контекст бота: набор use case'ов, доступных хендлерам."""

from dataclasses import dataclass

from avrora_bot.application.use_cases.calendar import CalendarUseCases
from avrora_bot.application.use_cases.legal import LegalUseCases
from avrora_bot.application.use_cases.one_time import OneTimeUseCases
from avrora_bot.application.use_cases.registration import RegistrationUseCases
from avrora_bot.application.use_cases.reports import ReportUseCases
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.application.use_cases.subscriptions import SubscriptionUseCases
from avrora_bot.application.use_cases.tariffs import TariffUseCases
from avrora_bot.application.use_cases.user_management import (
    UserManagementUseCases,
)


@dataclass(frozen=True, slots=True)
class BotContext:
    """Сгруппированные use case'ы приложения для VK-хендлеров."""

    registration: RegistrationUseCases
    legal: LegalUseCases
    roles: RoleUseCases
    tariffs: TariffUseCases
    subscriptions: SubscriptionUseCases
    one_time: OneTimeUseCases
    calendar: CalendarUseCases
    reports: ReportUseCases
    user_management: UserManagementUseCases
