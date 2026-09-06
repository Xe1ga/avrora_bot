"""Точка сборки и запуска приложения.

Последовательность старта: настройка логов → сборка контейнера → сидинг
справочных данных и bootstrap-администратора → запуск Long Poll.

Применение миграций (``alembic upgrade head``) выполняется отдельно на этапе
запуска контейнера (entrypoint), до старта бота.
"""

from avrora_bot.adapters.database.seed import (
    ensure_bootstrap_admin,
    seed_reference_data,
)
from avrora_bot.composition import Container, build_container
from avrora_bot.config import get_settings
from avrora_bot.logging_setup import configure_logging, get_logger

log = get_logger('app')


async def _bootstrap(container: Container) -> None:
    """Сидинг справочных данных и первого администратора."""
    async with container.uow_factory() as uow:
        await seed_reference_data(uow)
        await ensure_bootstrap_admin(
            uow, container.settings.bootstrap_admin_vk_id
        )
        await uow.commit()


async def run() -> None:
    """Асинхронная точка входа: инициализация и запуск бота."""
    settings = get_settings()
    configure_logging(settings.log_level)

    container = build_container(settings)
    container.report_dir.mkdir(parents=True, exist_ok=True)

    log.info('app.starting', group_id=settings.vk_group_id)
    await _bootstrap(container)

    if settings.vk_use_callback:
        log.warning(
            'app.callback_not_implemented',
            detail='Callback API вне периметра Этапа 1, используется Long Poll',
        )

    try:
        log.info('app.polling_start')
        await container.bot.run_polling()
    finally:
        await container.engine.dispose()
        log.info('app.stopped')
