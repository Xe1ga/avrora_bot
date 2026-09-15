"""Use case'ы работы с версиями юридических документов (ТЗ 3.6, 152-ФЗ)."""

from collections.abc import Callable
from dataclasses import dataclass

from avrora_bot.domain.entities import LegalDocument
from avrora_bot.domain.enums import LegalDocumentKind
from avrora_bot.domain.errors import NotFoundError
from avrora_bot.domain.ports.uow import UnitOfWork

UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class CurrentLegalDocuments:
    """Пара актуальных документов, предъявляемых при регистрации."""

    consent: LegalDocument
    privacy_policy: LegalDocument


class LegalUseCases:
    """Доступ к актуальным и историческим версиям документов о ПД."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def current_documents(self) -> CurrentLegalDocuments:
        """Возвращает актуальные версии согласия и политики обработки ПД.

        Версии регистрируются при старте приложения по файлам из
        ``docs/legal/`` (см. ``adapters.database.seed``).

        :raises NotFoundError: если документы ещё не зарегистрированы —
            без них согласие фиксировать не с чем, поэтому регистрация
            новых пользователей в этом случае недоступна.
        """
        async with self._uow_factory() as uow:
            consent = await uow.legal_documents.current(
                LegalDocumentKind.CONSENT
            )
            privacy_policy = await uow.legal_documents.current(
                LegalDocumentKind.PRIVACY_POLICY
            )
        if consent is None or privacy_policy is None:
            raise NotFoundError(
                'Документы об обработке персональных данных не '
                'опубликованы — регистрация временно недоступна. '
                'Сообщите администратору.'
            )
        return CurrentLegalDocuments(
            consent=consent, privacy_policy=privacy_policy
        )
