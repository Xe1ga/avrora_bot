"""Настройка структурированного логирования через structlog."""

import logging
import sys

import structlog


def configure_logging(level: str = 'INFO') -> None:
    """Конфигурирует structlog + стандартный logging.

    В контейнере логи пишутся в stdout (JSON-подобный формат при не-TTY,
    человекочитаемый — при TTY), что удовлетворяет требованию наблюдаемости
    (структурированные логи, доступные администратору).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format='%(message)s',
        stream=sys.stdout,
        level=log_level,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt='iso', utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if sys.stderr.isatty():
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Возвращает связанный логгер structlog."""
    return structlog.get_logger(name)
