"""Фабрика бота vkbottle."""

from pathlib import Path

from vkbottle import API, Bot, BuiltinStateDispenser

from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.gateway import VkbottleGateway
from avrora_bot.adapters.vk.handlers import register_handlers
from avrora_bot.adapters.vk.middlewares import make_rate_limit_middleware


def build_bot(
    api: API,
    ctx: BotContext,
    gateway: VkbottleGateway,
    *,
    rate_limit_per_sec: float,
    report_dir: Path,
) -> Bot:
    """Создаёт и настраивает бота: middleware и хендлеры.

    :param api: общий VK API-клиент (используется и ботом, и шлюзом).
    :param gateway: шлюз VK для проверки прав и отправки документов.
    """
    bot = Bot(api=api, state_dispenser=BuiltinStateDispenser())

    interval = 1.0 / rate_limit_per_sec if rate_limit_per_sec > 0 else 0.0
    bot.labeler.message_view.register_middleware(
        make_rate_limit_middleware(interval)
    )

    register_handlers(bot, ctx, gateway, report_dir)
    return bot
