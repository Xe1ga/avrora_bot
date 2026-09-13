"""Сервис журналирования административных действий (ТЗ 5.5).

Оборачивает запись в ``action_log`` и дублирует событие в структурированный
лог. Вызывается из use case'ов, изменяющих данные.
"""

from avrora_bot.domain.entities import ActionLogEntry
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.logging_setup import get_logger

log = get_logger('action_log')


async def record_action(
    uow: UnitOfWork,
    actor_vk_id: int,
    action: str,
    details: str | None = None,
) -> None:
    """Фиксирует действие в БД и структурированном логе.

    Запись выполняется в рамках уже открытой транзакции ``uow`` (commit —
    ответственность вызывающего use case).

    ВАЖНО: ``details`` — свободный текст и не маскируется автоматически
    (в отличие от известных ключей структурированного лога, см.
    ``logging_setup._redact_pii_processor``). В нём нельзя указывать ФИО,
    телефон и другие персональные данные — только vk_id, статусы, суммы
    и т.п.
    """
    await uow.action_log.add(
        ActionLogEntry(actor_vk_id=actor_vk_id, action=action, details=details)
    )
    log.info('action', actor_vk_id=actor_vk_id, action=action, details=details)
