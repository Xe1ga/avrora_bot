"""Точка сборки и запуска приложения.

Последовательность старта: настройка логов → сборка контейнера → сидинг
справочных данных, регистрация актуальных версий документов о ПД
(``docs/legal/``) и bootstrap-администратора → фоновая задача
автозавершения событий календаря → запуск Long Poll.

Применение миграций (``alembic upgrade head``) выполняется отдельно на этапе
запуска контейнера (entrypoint), до старта бота.
"""

import asyncio
import contextlib
from datetime import datetime
from zoneinfo import ZoneInfo

from avrora_bot.adapters.database.seed import (
    ensure_bootstrap_admin,
    seed_reference_data,
    sync_legal_documents,
)
from avrora_bot.application.use_cases.calendar import (
    complete_finished_events,
)
from avrora_bot.composition import Container, build_container
from avrora_bot.config import get_settings
from avrora_bot.domain.enums import LegalDocumentKind
from avrora_bot.logging_setup import configure_logging, get_logger

log = get_logger('app')

# Период фоновой задачи, переводящей прошедшие события в «выполнено».
_AUTO_COMPLETE_INTERVAL_SEC = 15 * 60
# Предел одного прохода: зависший запрос к БД не должен навсегда
# остановить автозавершение и удерживать соединение из пула.
_AUTO_COMPLETE_TIMEOUT_SEC = 2 * 60


async def _bootstrap(container: Container) -> None:
    """Сидинг справочных данных, документов о ПД и первого администратора."""
    settings = container.settings
    async with container.uow_factory() as uow:
        await seed_reference_data(uow)
        await sync_legal_documents(
            uow,
            settings.legal_docs_dir,
            urls={
                LegalDocumentKind.CONSENT: settings.pdn_consent_url,
                LegalDocumentKind.PRIVACY_POLICY: settings.privacy_policy_url,
            },
        )
        await ensure_bootstrap_admin(uow, settings.bootstrap_admin_vk_id)
        await uow.commit()


async def _auto_complete_events(container: Container) -> None:
    """Раз в 15 минут переводит прошедшие события календаря в «выполнено».

    Первый проход — сразу при старте: догоняет всё, что закончилось, пока
    бот был выключен. Ошибка или превышение таймаута одного прохода
    логируются и не останавливают задачу.
    """
    while True:
        try:
            tz = ZoneInfo(container.settings.tz)
            now = datetime.now(tz).replace(tzinfo=None)
            async with (
                asyncio.timeout(_AUTO_COMPLETE_TIMEOUT_SEC),
                container.uow_factory() as uow,
            ):
                completed = await complete_finished_events(uow, now)
                await uow.commit()
            if completed:
                log.info('calendar.auto_completed', count=completed)
        except TimeoutError:
            log.error(
                'calendar.auto_complete_timeout',
                timeout_sec=_AUTO_COMPLETE_TIMEOUT_SEC,
            )
        except Exception:
            log.exception('calendar.auto_complete_failed')
        await asyncio.sleep(_AUTO_COMPLETE_INTERVAL_SEC)


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

    auto_complete = asyncio.create_task(_auto_complete_events(container))
    try:
        log.info('app.polling_start')
        await container.bot.run_polling()
    finally:
        auto_complete.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await auto_complete
        await container.engine.dispose()
        log.info('app.stopped')
