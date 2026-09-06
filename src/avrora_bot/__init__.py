"""Пакет чат-бота волейбольного клуба «Аврора»."""

import asyncio


def main() -> None:
    """Синхронная точка входа (console script)."""
    # Ленивый импорт: не тянем vkbottle/БД при простом импорте пакета.
    from avrora_bot.app import run  # noqa: PLC0415

    asyncio.run(run())
