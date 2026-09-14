"""Регистрация всех групп хендлеров бота."""

from pathlib import Path

from vkbottle import Bot

from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.gateway import VkbottleGateway
from avrora_bot.adapters.vk.handlers import (
    admin,
    calendar,
    common,
    one_time,
    registration,
    reports,
    subscriptions,
    user_edit,
)


def register_handlers(
    bot: Bot,
    ctx: BotContext,
    gateway: VkbottleGateway,
    report_dir: Path,
    *,
    privacy_policy_url: str,
    pdn_consent_url: str,
    pdn_consent_version: str,
    schedule_url: str,
) -> None:
    """Подключает все хендлеры к боту.

    Порядок важен: специфичные текстовые команды регистрируются раньше
    общих, а FSM-хендлеры регистрации — до широких текстовых правил.
    """
    registration.register(
        bot,
        ctx,
        privacy_policy_url=privacy_policy_url,
        pdn_consent_url=pdn_consent_url,
        pdn_consent_version=pdn_consent_version,
    )
    user_edit.register(bot, ctx)
    admin.register(bot, ctx)
    subscriptions.register(bot, ctx)
    one_time.register(bot, ctx)
    calendar.register(bot, ctx)
    reports.register(bot, ctx, gateway, report_dir)
    common.register(bot, ctx, schedule_url=schedule_url)
