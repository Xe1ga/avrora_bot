"""Доменные исключения."""


class DomainError(Exception):
    """Базовое доменное исключение."""


class ValidationError(DomainError):
    """Нарушение доменных инвариантов (некорректные входные данные)."""


class PermissionDeniedError(DomainError):
    """Недостаточно прав для выполнения действия."""


class NotFoundError(DomainError):
    """Запрашиваемая сущность не найдена."""


class AlreadyExistsError(DomainError):
    """Сущность с такими уникальными признаками уже существует."""
